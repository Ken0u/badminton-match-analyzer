"""Synthetic motion/pose inputs for software QA, not real match truth."""

import numpy as np


def motion_scene(kind="contact", seed=0, missing=(), variable_rate=False):
    rng = np.random.default_rng(seed)
    times = np.arange(45) / 30
    if variable_rate:
        times = np.r_[0, np.cumsum([0.02, 0.04] * 22)]
    knot = times[20] + 0.37 * (times[21] - times[20])
    rows, players = [], []
    for i, t in enumerate(times):
        dt = t - knot
        if kind == "contact":
            velocity = np.array([220, -60]) if dt < 0 else np.array([-180, 40])
            point = np.array([320.0, 160.0]) + velocity * dt
        elif kind == "apex":
            point = np.array([320 + 15 * dt, 160 + 600 * dt**2])
        elif kind == "straight":
            point = np.array([320 + 200 * dt, 160 + 40 * dt])
        else:
            point = np.array([320.0, 160.0])
        # Independent localization error plus finite heatmap-cell resolution.
        point = np.round((point + rng.normal(0, 0.7, 2)) / 1.25) * 1.25
        visible = i not in missing
        rows.append(
            {
                "frame": i,
                "time_s": float(t),
                "shuttle": {
                    "visible": visible,
                    "x": float(point[0]) if visible else None,
                    "y": float(point[1]) if visible else None,
                    "repaired": False,
                },
            }
        )
        keypoints = [[0, 0, 0] for _ in range(17)]
        keypoints[9] = [320 + 100 * dt, 160, 0.95]
        players.append(
            {
                "frame": i,
                "time_s": float(t),
                "players": [
                    {"track_id": 1, "box": [260, 100, 380, 280], "keypoints": keypoints}
                ],
            }
        )
    return {"frames": rows}, {"frames": players}, {"width": 640, "height": 360}, knot
