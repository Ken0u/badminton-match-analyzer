"""Observed flight and actor context for experimental stroke learning.

No event, family, side, source-foot label or persistent identity enters a value.
Court projection is an image-space foot hint, not a measured physical position.
"""

import bisect
import math
from copy import deepcopy

import numpy as np

from .calibration_context import effective_annotations
from .contact_features import build_contact_features, visible
from .rallies import _court_position, context_signature
from .scene_review import plain, reviewed_run
from .schemas import Calibration

FLIGHT_OFFSETS = (-0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20)
EXTENDED_FLIGHT_OFFSETS = (-0.5, -0.4, -0.3, *FLIGHT_OFFSETS, 0.3, 0.4, 0.5)
BODY_DIM = 254
FLIGHT_DIM = 12
FEATURE_DIM = BODY_DIM + len(FLIGHT_OFFSETS) * FLIGHT_DIM + 6 + 3
RECIPE = {
    "name": "observed-stroke-flight-context-v2",
    "feature_dim": FEATURE_DIM,
    "flight_offsets_s": FLIGHT_OFFSETS,
    "maximum_sample_error_s": 0.025,
    "maximum_source_step_s": 0.1,
    "maximum_anchor_distance_s": 0.08,
    "maximum_supported_offset_s": 0.5,
    "body": "Two observed 126-value arm windows and two masks",
    "flight": [
        "visible",
        "actual_dt",
        "x_fraction",
        "y_fraction",
        "anchor_dx_diagonals",
        "anchor_dy_diagonals",
        "velocity_available",
        "vx_diagonals_s",
        "vy_diagonals_s",
        "confidence",
        "component_count_over_8",
        "speed_diagonals_s",
    ],
    "court": [
        "available",
        "foot_x_hint",
        "foot_y_hint",
        "ankles_used",
        "box_width_fraction",
        "box_height_fraction",
    ],
    "anchor": ["available", "actual_dt", "confidence"],
    "missing_points": "Masked; never interpolated or treated as contact locations",
    "context": "Complete body, flight velocity and transitive selection lineage",
}


def _finite(value, default=0.0):
    return (
        float(value)
        if isinstance(value, int | float) and math.isfinite(value)
        else default
    )


class StrokeContext:
    """Build source-guarded inputs once, then pack any observed actor/time."""

    def __init__(
        self,
        video,
        player_run,
        shuttle_run,
        annotations,
        *,
        flight_offsets=FLIGHT_OFFSETS,
    ):
        self.offsets = tuple(float(offset) for offset in flight_offsets)
        if (
            not 3 <= len(self.offsets) <= 31
            or not all(
                math.isfinite(offset) and abs(offset) <= 0.5 for offset in self.offsets
            )
            or tuple(sorted(set(self.offsets))) != self.offsets
            or 0.0 not in self.offsets
            or not self.offsets[0] < 0 < self.offsets[-1]
        ):
            raise ValueError(
                "Flight offsets must be ordered, unique and span zero within +/-0.5s"
            )
        self.feature_dim = BODY_DIM + len(self.offsets) * FLIGHT_DIM + 9
        self.recipe = RECIPE | {
            "flight_offsets_s": self.offsets,
            "feature_dim": self.feature_dim,
        }
        self.video = deepcopy(video)
        self.doc = deepcopy(plain(annotations))
        for calibration in self.doc.get("calibrations", []):
            Calibration.model_validate(calibration)
        self.players = reviewed_run(player_run, self.doc)
        self.shuttle = reviewed_run(shuttle_run, self.doc)
        for run in (self.players, self.shuttle):
            if run["requires_tracking_rerun"]:
                if run.get("requires_court_tracking_rerun"):
                    raise ValueError(
                        "Court calibration changed inputs; rerun player tracking"
                    )
                raise ValueError("Camera corrections changed inputs; rerun tracking")
        self.doc = effective_annotations(self.doc, self.players)
        expected = context_signature(
            self.doc, self.players["start_frame"], self.players["end_frame"]
        )["court"]
        if self.players.get("calibration_signature") != expected:
            raise ValueError(
                "Court calibration changed or lacks provenance; rerun players"
            )
        self.body = build_contact_features(video, self.players, self.shuttle)
        self.rows = self.shuttle["frames"]
        self.times, self.frames = self.body["times"], self.body["frames"]
        for run in (self.players, self.shuttle):
            if (
                not 0
                <= run["start_frame"]
                == self.frames[0]
                < run["end_frame"]
                == self.frames[-1] + 1
                <= video["frame_count"]
            ):
                raise ValueError(
                    "Perception range must cover its complete source frames"
                )
        self.diagonal = math.hypot(video["width"], video["height"])
        self.cuts = set(self.players["cut_frames"]) | set(self.shuttle["cut_frames"])
        self.blocked = np.asarray(
            [
                p.get("scene", "live") != "live"
                or s.get("scene", "live") != "live"
                or not p.get("calibration_valid", False)
                or s["shuttle"].get("selection_context_excluded", False)
                for p, s in zip(self.players["frames"], self.rows)
            ]
        )
        self.flight, self.dependencies = [], []
        for i, row in enumerate(self.rows):
            velocity = np.zeros(2, np.float64)
            seen = visible(row)
            has_velocity = (
                i > 0
                and seen
                and visible(self.rows[i - 1])
                and 0 < self.times[i] - self.times[i - 1] <= 0.1 + 1e-9
                and row["frame"] not in self.cuts
            )
            used = [i - 1, i] if has_velocity else [i]
            if has_velocity:
                velocity = np.asarray(
                    [
                        row["shuttle"][axis] - self.rows[i - 1]["shuttle"][axis]
                        for axis in ("x", "y")
                    ]
                ) / ((self.times[i] - self.times[i - 1]) * self.diagonal)
            left, right = int(self.frames[min(used)]), int(row["frame"] + 1)
            for index in used:
                if not visible(self.rows[index]):
                    continue
                point = self.rows[index]["shuttle"]
                a = point.get("selection_context_start_frame", int(self.frames[index]))
                b = point.get(
                    "selection_context_end_frame", int(self.frames[index] + 1)
                )
                if (
                    type(a) is not int
                    or type(b) is not int
                    or not self.frames[0]
                    <= a
                    <= self.frames[index]
                    < b
                    <= self.frames[-1] + 1
                ):
                    raise ValueError(
                        "Flight selection lineage must lie inside the observed run"
                    )
                left, right = min(left, a), max(right, b)
            self.dependencies.append((left, right))
            self.flight.append((seen, has_velocity, np.clip(velocity, -6, 6)))

    def _indices(self, origin):
        result = []
        for offset in self.offsets:
            target = origin + offset
            pos = bisect.bisect_left(self.times, target)
            options = [p for p in (pos - 1, pos) if 0 <= p < len(self.times)]
            index = min(options, key=lambda p: abs(self.times[p] - target))
            if abs(self.times[index] - target) > 0.025 + 1e-9:
                return None
            result.append(index)
        return result

    def pack(self, index, track_id):
        if not isinstance(index, int | np.integer) or not 0 <= index < len(self.frames):
            raise ValueError("Navigation index must identify an observed source frame")
        slots = np.flatnonzero(
            self.body["arm_mask"][index]
            & (self.body["arm_ids"][index, :, 0] == track_id)
        )
        if not len(slots):
            return None
        origin = self.times[index]
        indices = self._indices(origin)
        if indices is None:
            return None
        anchors = [
            i
            for i, row in enumerate(self.rows)
            if abs(self.times[i] - origin) <= 0.08 + 1e-9 and visible(row)
        ]
        anchor = (
            min(anchors, key=lambda i: (abs(self.times[i] - origin), i))
            if anchors
            else None
        )
        used = indices + ([anchor] if anchor is not None else [])
        left = min(
            int(self.body["context"][index, 0]),
            *(self.dependencies[i][0] for i in used),
        )
        right = max(
            int(self.body["context"][index, 1]),
            *(self.dependencies[i][1] for i in used),
        )
        lo, hi = int(left - self.frames[0]), int(right - self.frames[0])
        if (
            self.blocked[lo:hi].any()
            or any(left < cut < right for cut in self.cuts)
            or np.max(np.diff(self.times[lo:hi])) > 0.1 + 1e-9
        ):
            return None
        if not any(
            c["start_frame"] <= left and right <= c["end_frame"]
            for c in self.doc.get("calibrations", [])
        ):
            return None
        arms, mask = np.zeros((2, 126), np.float32), np.zeros(2, np.float32)
        for slot in slots:
            side = int(self.body["arm_ids"][index, slot, 1])
            arms[side], mask[side] = self.body["x"][index, slot], 1
        values = [*arms.ravel(), *mask]
        for i in indices:
            seen, has_velocity, velocity = self.flight[i]
            point = self.rows[i]["shuttle"]
            sample = np.zeros(FLIGHT_DIM)
            sample[1] = self.times[i] - origin
            if seen:
                sample[0] = 1
                sample[2:4] = (
                    point["x"] / self.video["width"],
                    point["y"] / self.video["height"],
                )
                if anchor is not None:
                    sample[4:6] = [
                        (point[a] - self.rows[anchor]["shuttle"][a]) / self.diagonal
                        for a in ("x", "y")
                    ]
                sample[6:9] = has_velocity, *velocity
                sample[9] = np.clip(_finite(point.get("confidence")), 0, 1)
                sample[10] = np.clip(_finite(point.get("component_count")), 0, 8) / 8
                sample[11] = np.linalg.norm(velocity)
            values.extend(sample)
        actor = [
            p
            for p in self.players["frames"][index]["players"]
            if p.get("track_id") == track_id
        ]
        court = np.zeros(6)
        if len(actor) == 1:
            actor = actor[0]
            box, keypoints = actor["box"], actor.get("keypoints", [])
            ankles = [
                keypoints[k]
                for k in (15, 16)
                if k < len(keypoints)
                and len(keypoints[k]) >= 3
                and all(math.isfinite(v) for v in keypoints[k][:3])
                and keypoints[k][2] >= 0.3
            ]
            foot = (
                np.mean([p[:2] for p in ankles], axis=0)
                if len(ankles) == 2
                else [(box[0] + box[2]) / 2, box[3]]
            )
            position = _court_position(
                foot, int(self.frames[index]), self.doc, self.video
            )
            if position is not None and np.isfinite(position).all():
                court[:4] = 1, *np.clip(position, -2, 3), len(ankles) == 2
            court[4:] = (
                (box[2] - box[0]) / self.video["width"],
                (box[3] - box[1]) / self.video["height"],
            )
        values.extend(court)
        values.extend(
            [
                1,
                self.times[anchor] - origin,
                np.clip(_finite(self.rows[anchor]["shuttle"].get("confidence")), 0, 1),
            ]
            if anchor is not None
            else [0, 0, 0]
        )
        result = np.asarray(values, np.float32)
        if result.shape != (self.feature_dim,) or not np.isfinite(result).all():
            raise ValueError("Stroke features must be finite and match their recipe")
        return {
            "features": result,
            "navigation_frame": int(self.frames[index]),
            "context_start_frame": left,
            "context_end_frame": right,
            "anchor_observation_frame": int(self.frames[anchor])
            if anchor is not None
            else None,
        }
