"""Learned contact, hitter, stroke-family and side suggestions for singles.

One temporal model reads the players' poses and the shuttle track across a
camera view and marks racket contacts with who hit, what stroke and which side,
and whether a serve was short or long. Views where no court was found (replays
from other angles, close-ups, the crowd) are labelled non-play and skipped.
It is trained by training/train_events.py and used only when its checkpoint
(events.pt) is present in the weights folder. Outputs are review suggestions.
"""

import hashlib

import numpy as np

from .config import WEIGHTS

FAMILIES = ("serve", "clear", "drive", "smash", "net", "drop", "lift", "other")
SIDES = ("forehand", "backhand")
SERVES = ("short", "long")
COURT_ENDS = ("far", "near")
PLAYER = 17 * 3 + 5
FEATURES = 2 * PLAYER + 6
TRAINED_FPS = 30.0
CHECKPOINT = "events.pt"
METHOD = "learned singles event model v2"


def checkpoint_path():
    return WEIGHTS / CHECKPOINT


def checkpoint_sha256():
    path = checkpoint_path()
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def available(video):
    return video.get("mode") == "singles" and checkpoint_path().is_file()


def _player_vector(person, width, height):
    vector = np.zeros(PLAYER, np.float32)
    if person is None:
        return vector
    points = np.asarray(person["keypoints"], np.float32).reshape(17, 3)
    x1, y1, x2, y2 = person["box"]
    vector[0:51:3] = points[:, 0] / width
    vector[1:51:3] = points[:, 1] / height
    vector[2:51:3] = points[:, 2]
    vector[51:55] = (x1 / width, y1 / height, x2 / width, y2 / height)
    vector[55] = 1
    return vector


def court_slots(players, height):
    """Assign up to two observed people to the far and near court ends."""
    people = [p for p in players if len(p.get("keypoints", [])) == 17]
    people = sorted(people, key=lambda p: -p["confidence"])[:2]
    people.sort(key=lambda p: p["box"][3])
    if len(people) == 2:
        return people[0], people[1]
    if people:
        # A lone person is placed by which half of the image their feet are in.
        return (
            (people[0], None)
            if people[0]["box"][3] < height * 0.55
            else (
                None,
                people[0],
            )
        )
    return None, None


def observations(player_rows, shuttle_points, width, height):
    """Per-frame poses and shuttle position, before motion features."""
    count = len(player_rows)
    values = np.zeros((count, 2 * PLAYER + 3), np.float32)
    tracks = []
    for index, (row, ball) in enumerate(zip(player_rows, shuttle_points)):
        far, near = court_slots(row["players"], height)
        values[index, :PLAYER] = _player_vector(far, width, height)
        values[index, PLAYER : 2 * PLAYER] = _player_vector(near, width, height)
        if ball.get("visible") and ball.get("x") is not None:
            values[index, 2 * PLAYER :] = (ball["x"] / width, ball["y"] / height, 1)
        tracks.append(
            (
                far.get("track_id") if far else None,
                near.get("track_id") if near else None,
            )
        )
    return values, tracks


def with_motion(values):
    """Append per-step shuttle velocity across gaps of at most three steps."""
    inputs = np.zeros((len(values), FEATURES), np.float32)
    inputs[:, : 2 * PLAYER + 3] = values
    previous = None
    for index in range(len(values)):
        x, y, seen = values[index, 2 * PLAYER :]
        if not seen:
            continue
        if previous is not None and index - previous[0] <= 3:
            gap = index - previous[0]
            inputs[index, 2 * PLAYER + 3 :] = (
                (x - previous[1]) / gap,
                (y - previous[2]) / gap,
                1,
            )
        previous = (index, x, y)
    return inputs


def clip_inputs(player_rows, shuttle_points, width, height):
    """Training-time features for one rally clip at its native frame rate."""
    values, _ = observations(player_rows, shuttle_points, width, height)
    return with_motion(values)


def resample(values, times, rate=TRAINED_FPS):
    """Bring a view onto the trained frame rate without inventing detections.

    Coordinates are interpolated only between two frames that both observe the
    same thing; otherwise the nearer frame is copied. Returns the resampled
    values and, for each output step, the index of its nearest source frame.
    """
    times = np.asarray(times, np.float64)
    steps = max(1, round((times[-1] - times[0]) * rate) + 1)
    grid = times[0] + np.arange(steps) / rate
    right = np.clip(np.searchsorted(times, grid), 1, len(times) - 1)
    left = right - 1
    span = np.maximum(times[right] - times[left], 1e-9)
    weight = np.clip((grid - times[left]) / span, 0, 1).astype(np.float32)[:, None]
    nearest = np.where(weight[:, 0] < 0.5, left, right)
    out = values[nearest].copy()
    for start, flag in ((0, 55), (PLAYER, PLAYER + 55), (2 * PLAYER, 2 * PLAYER + 2)):
        stop = flag + 1
        both = (values[left, flag] > 0) & (values[right, flag] > 0)
        mixed = (
            values[left, start:stop] * (1 - weight) + values[right, start:stop] * weight
        )
        out[both, start:stop] = mixed[both]
    return out, nearest


def _peaks(probability, threshold, radius=4):
    found = []
    for index in np.argsort(-probability):
        if probability[index] < threshold:
            break
        if all(abs(index - other) > radius for other in found):
            found.append(int(index))
    return sorted(found)


def _views(player_rows, cuts):
    """Split frames into runs that share one camera view."""
    start = 0
    for index in range(1, len(player_rows) + 1):
        if index == len(player_rows) or (
            player_rows[index]["frame"] in cuts
            or player_rows[index].get("camera_segment_start_frame")
            != player_rows[index - 1].get("camera_segment_start_frame")
            or player_rows[index]["frame"] != player_rows[index - 1]["frame"] + 1
        ):
            yield start, index
            start = index


def run_cuts(player_run, shuttle_run):
    return set(player_run.get("cut_frames", [])) | set(
        shuttle_run.get("cut_frames", [])
    )


def view_scenes(player_run, cuts=()):
    """Suggest which camera views show the match from the main court camera.

    The court detector finds the full court only in the main broadcast view, so
    a view where most frames have no court is a replay from another angle, a
    close-up or the crowd. A slow-motion replay from the main camera still
    looks like play. If no view in the run has a court, nothing is judged:
    the camera angle may simply be one the court detector cannot read.
    """
    rows = player_run["frames"]
    judged = any(r.get("calibration_valid") for r in rows)
    scenes = []
    for start, stop in _views(rows, set(cuts)):
        share = float(
            np.mean([bool(r.get("calibration_valid")) for r in rows[start:stop]])
        )
        scenes.append(
            {
                "start_frame": rows[start]["frame"],
                "end_frame": rows[stop - 1]["frame"] + 1,
                "scene": "unknown"
                if not judged
                else "live"
                if share >= 0.5
                else "non_play",
                "court_frame_share": round(share, 3),
                "reviewed": False,
            }
        )
    return scenes


def predict_events(video, player_run, shuttle_run):
    """Suggest contacts for one processed window. Returns a list of dicts."""
    import torch

    from .event_network import EventModel

    player_rows, shuttle_rows = player_run["frames"], shuttle_run["frames"]
    if [r["frame"] for r in player_rows] != [r["frame"] for r in shuttle_rows]:
        raise ValueError("Player and shuttle runs must cover the same frames")
    saved = torch.load(checkpoint_path(), map_location="cpu", weights_only=True)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = EventModel().to(device).eval()
    # Checkpoints trained before serve types existed lack that output.
    serve_types = "heads.serve.weight" in saved["state"]
    model.load_state_dict(saved["state"], strict=serve_types)
    threshold = float(saved["threshold"])
    cuts = run_cuts(player_run, shuttle_run)
    skipped = {
        s["start_frame"]
        for s in view_scenes(player_run, cuts)
        if s["scene"] == "non_play"
    }
    width, height = video["width"], video["height"]
    fps = float(video.get("fps") or TRAINED_FPS)
    events = []
    try:
        for start, stop in _views(player_rows, cuts):
            if stop - start < 8 or player_rows[start]["frame"] in skipped:
                continue
            rows = player_rows[start:stop]
            values, tracks = observations(
                rows, [r["shuttle"] for r in shuttle_rows[start:stop]], width, height
            )
            if not values[:, [55, PLAYER + 55]].any():
                continue
            if abs(fps - TRAINED_FPS) > 0.5:
                values, nearest = resample(values, [r["time_s"] for r in rows])
            else:
                nearest = np.arange(len(rows))
            with torch.inference_mode():
                out = model(torch.from_numpy(with_motion(values))[None].to(device))
            hit = torch.sigmoid(out["hit"][0, :, 0]).cpu().numpy()
            scores = {
                name: torch.softmax(out[name][0].float(), -1).cpu().numpy()
                for name in ("hitter", "family", "side", "serve")
            }
            for step in _peaks(hit, threshold):
                row = rows[int(nearest[step])]
                end = int(scores["hitter"][step].argmax())
                family = int(scores["family"][step].argmax())
                side = int(scores["side"][step].argmax())
                serve = int(scores["serve"][step].argmax())
                typed = serve_types and FAMILIES[family] == "serve"
                events.append(
                    {
                        "frame": row["frame"],
                        "time_s": row["time_s"],
                        "score": float(hit[step]),
                        "court_end": COURT_ENDS[end],
                        "court_end_score": float(scores["hitter"][step][end]),
                        "track_id": tracks[int(nearest[step])][end],
                        "kind": "serve" if FAMILIES[family] == "serve" else "shot",
                        "family": FAMILIES[family],
                        "family_score": float(scores["family"][step][family]),
                        "family_scores": {
                            name: float(value)
                            for name, value in zip(FAMILIES, scores["family"][step])
                        },
                        "side": SIDES[side],
                        "side_score": float(scores["side"][step][side]),
                        "serve_type": SERVES[serve] if typed else None,
                        "serve_type_score": float(scores["serve"][step][serve])
                        if typed
                        else None,
                        "view_start_frame": rows[0]["frame"],
                        "view_end_frame": rows[-1]["frame"] + 1,
                    }
                )
    finally:
        del model
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
    # Resampling can map two steps onto one source frame; keep the stronger.
    best = {}
    for event in events:
        if event["frame"] not in best or event["score"] > best[event["frame"]]["score"]:
            best[event["frame"]] = event
    return [best[frame] for frame in sorted(best)]


def contact_candidates(events):
    """Contact suggestions in the shape the review editor already understands."""
    return [
        {
            "id": f"contact-{e['frame']}",
            "frame": e["frame"],
            "time_s": e["time_s"],
            "start_frame": e["frame"],
            "end_frame": e["frame"],
            "start_time_s": e["time_s"],
            "end_time_s": e["time_s"],
            "context_start_frame": max(e["view_start_frame"], e["frame"] - 15),
            "context_end_frame": min(e["view_end_frame"], e["frame"] + 16),
            "interval_bounds": "inclusive",
            "timing": "learned_contact",
            "score": round(e["score"], 3),
            "track_id": e["track_id"],
            "player_id": None,
            "evidence_source": "learned_event_model",
            "evidence": {"court_end": e["court_end"]},
            "reason": f"learned contact by the {e['court_end']} player",
            "reviewed": False,
            "learned": {
                k: e.get(k)
                for k in (
                    "kind",
                    "family",
                    "family_score",
                    "family_scores",
                    "side",
                    "side_score",
                    "court_end",
                    "court_end_score",
                    "track_id",
                    "serve_type",
                    "serve_type_score",
                )
            },
        }
        for e in events
    ]


def stroke_candidates(targets, contact_run):
    """Stroke suggestions for the recognition targets that came from the model."""
    learned = {
        c["id"]: c["learned"] | {"time_s": c["time_s"]}
        for c in contact_run.get("candidates", [])
        if "learned" in c
    }
    results = []
    for target in targets:
        info = learned.get(target.get("contact_candidate_id"))
        if info is None:
            continue
        ranked = sorted(info["family_scores"].items(), key=lambda item: -item[1])[:3]
        serve = info["kind"] == "serve"
        name = (
            " ".join(filter(None, (info.get("serve_type"), "serve")))
            if serve
            else info["family"]
        )
        results.append(
            target
            | {
                "time_s": info["time_s"],
                "status": "predicted",
                "kind": info["kind"],
                "family": None if serve else info["family"],
                "family_score": info["family_score"],
                "family_scores": info["family_scores"],
                "top_classes": [
                    {
                        "kind": "serve" if name == "serve" else "shot",
                        "family": None if name == "serve" else name,
                        "score": value,
                    }
                    for name, value in ranked
                ],
                "side": info["side"],
                "side_score": info["side_score"],
                "side_status": "predicted",
                "serve_type": info.get("serve_type"),
                "serve_type_score": info.get("serve_type_score"),
                "hitter_court_end": info["court_end"],
                "hitter_hint": {
                    "court_end": info["court_end"],
                    "track_id": info["track_id"],
                    "player_id": None,
                },
                "reason": f"learned {name} "
                f"({info['family_score']:.2f}) by the {info['court_end']} player",
            }
        )
    return results
