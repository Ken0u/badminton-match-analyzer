"""Conservative, reviewable contact proposals from raw shuttle motion and pose."""

import bisect
import math

import numpy as np


def _hitter_hint(point, players, diagonal):
    best = None
    for player in players:
        keypoints = player.get("keypoints", [])
        wrists = [
            keypoints[i]
            for i in (9, 10)
            if i < len(keypoints) and len(keypoints[i]) > 2 and keypoints[i][2] >= 0.3
        ]
        x1, y1, x2, y2 = player["box"]
        box_distance = math.hypot(
            max(x1 - point[0], 0, point[0] - x2), max(y1 - point[1], 0, point[1] - y2)
        )
        wrist_distance = min(
            (math.hypot(p[0] - point[0], p[1] - point[1]) for p in wrists),
            default=float("inf"),
        )
        # Allow the racket's reach beyond the hand; box proximity is a fallback.
        distance = min(wrist_distance, box_distance + diagonal * 0.02)
        if best is None or distance < best[0]:
            best = (distance, player)
    if best is None or best[0] > diagonal * 0.075:
        return None
    return best


def propose_contacts(shuttle_run, player_run, video):
    rows = shuttle_run["frames"]
    players = player_run["frames"] if player_run else []
    player_times = [r["time_s"] for r in players]
    diagonal = math.hypot(video["width"], video["height"])
    candidates = []
    for i in range(3, len(rows) - 3):
        window = rows[i - 3 : i + 4]
        if any(
            not r["shuttle"]["visible"] or r["shuttle"].get("repaired") for r in window
        ):
            continue
        times = np.asarray([r["time_s"] for r in window])
        if np.any(np.diff(times) <= 0) or np.max(np.diff(times)) > 0.1:
            continue
        points = np.asarray([[r["shuttle"]["x"], r["shuttle"]["y"]] for r in window])
        if not np.isfinite(points).all():
            continue
        # Local least-squares velocities respect variable source-frame durations.
        before = np.polyfit(times[:4] - times[3], points[:4], 1)[0]
        after = np.polyfit(times[3:] - times[3], points[3:], 1)[0]
        speed_before, speed_after = (
            float(np.linalg.norm(before)),
            float(np.linalg.norm(after)),
        )
        if min(speed_before, speed_after) < diagonal * 0.025:
            continue
        if max(speed_before, speed_after) > diagonal * 6:
            continue
        cosine = float(
            np.clip(np.dot(before, after) / (speed_before * speed_after), -1, 1)
        )
        angle = math.degrees(math.acos(cosine))
        ratio = max(speed_before, speed_after) / min(speed_before, speed_after)
        if angle < 35 and ratio < 2.5:
            continue
        hint = None
        if players:
            p = bisect.bisect_left(player_times, times[3])
            nearest = min(
                (j for j in (p - 1, p) if 0 <= j < len(players)),
                key=lambda j: abs(player_times[j] - times[3]),
            )
            if abs(player_times[nearest] - times[3]) > 0.08:
                continue
            hint = _hitter_hint(points[3], players[nearest]["players"], diagonal)
            if hint is None:
                continue
        proximity = 1 - min(1, hint[0] / (diagonal * 0.075)) if hint else 0
        score = min(
            1,
            0.55 * min(1, angle / 120)
            + 0.2 * min(1, (ratio - 1) / 2)
            + 0.25 * proximity,
        )
        candidates.append(
            {
                "id": f"contact-{rows[i]['frame']}",
                "frame": rows[i]["frame"],
                "time_s": rows[i]["time_s"],
                "score": round(score, 3),
                "angle_deg": round(angle, 1),
                "speed_ratio": round(ratio, 2),
                "track_id": hint[1]["track_id"] if hint else None,
                "player_id": None,
                "reason": "motion change near player"
                if hint
                else "motion change; hitter unconfirmed",
                "reviewed": False,
            }
        )
    # Suppress adjacent frames around one motion change without crossing missing data.
    selected = []
    for candidate in sorted(candidates, key=lambda c: c["score"], reverse=True):
        if all(abs(candidate["time_s"] - c["time_s"]) >= 0.16 for c in selected):
            selected.append(candidate)
    selected.sort(key=lambda c: c["frame"])
    return selected
