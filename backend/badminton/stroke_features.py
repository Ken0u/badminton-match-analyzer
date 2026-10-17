"""Source-aligned adaptation to the published BST-0 30-frame input contract.

The checkpoint was trained with MMPose COCO-17. This adapter uses YOLO COCO-17;
that pose-estimator domain shift needs measured validation, not an equivalence
claim. Raw track artifacts are never interpolated or modified.
"""

import bisect
import math

import cv2
import numpy as np

SEQUENCE_LENGTH = 30
BONES = (
    (0, 1),
    (0, 2),
    (1, 2),
    (1, 3),
    (2, 4),
    (3, 5),
    (4, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 6),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
)
# Source order is get_stroke_types('Both'), unmerged ShuttleSet, pinned upstream.
SOURCE_TYPES = (
    ("net shot", "shot", "net"),
    ("return net", "shot", "other"),
    ("smash", "shot", "smash"),
    ("wrist smash", "shot", "other"),
    ("lob", "shot", "lift"),
    ("defensive return lob", "shot", "lift"),
    ("clear", "shot", "clear"),
    ("drive", "shot", "drive"),
    ("back-court drive", "shot", "drive"),
    ("drop", "shot", "drop"),
    ("passive drop", "shot", "drop"),
    ("push", "shot", "other"),
    ("rush", "shot", "other"),
    ("defensive return drive", "shot", "drive"),
    ("cross-court net shot", "shot", "net"),
    ("short service", "serve", None),
    ("long service", "serve", None),
)


def source_classes():
    return [
        {
            "index": offset + i,
            "court_end": end,
            "source_type": name,
            "kind": kind,
            "family": family,
        }
        for offset, end in ((0, "far"), (17, "near"))
        for i, (name, kind, family) in enumerate(SOURCE_TYPES)
    ] + [
        {
            "index": 34,
            "court_end": None,
            "source_type": "unknown",
            "kind": "shot",
            "family": "unknown",
        }
    ]


def summarize_probabilities(probabilities):
    values = np.asarray(probabilities, dtype=np.float64)
    if (
        values.shape != (35,)
        or not np.isfinite(values).all()
        or np.any(values < 0)
        or not math.isclose(float(values.sum()), 1, abs_tol=1e-5)
    ):
        raise ValueError("Classifier must return 35 finite normalized probabilities")
    classes = source_classes()
    families = dict.fromkeys(
        ("clear", "lift", "net", "drop", "smash", "drive", "other", "unknown", "serve"),
        0.0,
    )
    for label, probability in zip(classes, values, strict=True):
        families["serve" if label["kind"] == "serve" else label["family"]] += float(
            probability
        )
    selected = max(families, key=families.get)
    # The top individual subtype can belong to a different family/court end.
    ends = dict.fromkeys(("far", "near"), 0.0)
    for label, probability in zip(classes, values, strict=True):
        family = "serve" if label["kind"] == "serve" else label["family"]
        if family == selected and label["court_end"] in ends:
            ends[label["court_end"]] += float(probability)
    hitter_end = max(ends, key=ends.get) if ends["far"] != ends["near"] else None
    ranked = sorted(range(35), key=lambda index: float(values[index]), reverse=True)[:3]
    return {
        "kind": "serve" if selected == "serve" else "shot",
        "family": None if selected == "serve" else selected,
        "family_score": families[selected],
        "family_scores": families,
        "side": "unknown",
        "hitter_court_end": hitter_end,
        "top_classes": [
            classes[index] | {"score": float(values[index])} for index in ranked
        ],
    }


def normalize_joints(points, box):
    """Match upstream center-aligned, box-diagonal COCO normalization."""
    points, box = (
        np.asarray(points, dtype=np.float64),
        np.asarray(box, dtype=np.float64),
    )
    diagonal = np.linalg.norm(box[2:] - box[:2])
    if (
        points.shape != (17, 2)
        or not np.isfinite(points).all()
        or not np.isfinite(box).all()
        or np.any(box[2:] <= box[:2])
        or diagonal <= 0
    ):
        raise ValueError(
            "Pose normalization requires finite COCO-17 points and a valid box"
        )
    normalized = np.where(points != 0, (points - box[:2]) / diagonal, 0.0)
    # Upstream also shifts zero-coordinate entries here; preserve that contract.
    return normalized - (box[2:] - box[:2]) / (2 * diagonal)


def pack_sequence(joints, shuttle):
    """Use upstream temporal decimation/zero padding and elementwise bone masks."""
    length = len(joints)
    if not length or length != len(shuttle):
        raise ValueError(
            "A stroke clip requires aligned nonempty pose and shuttle rows"
        )
    selected = np.arange(length)
    if length > SEQUENCE_LENGTH:
        stride = length // SEQUENCE_LENGTH + int(
            length % SEQUENCE_LENGTH > SEQUENCE_LENGTH // 2
        )
        selected = selected[::stride][:SEQUENCE_LENGTH]
    joints = np.asarray(joints, dtype=np.float32)[selected]
    shuttle = np.asarray(shuttle, dtype=np.float32)[selected]
    bones = np.stack(
        [
            np.where(
                (joints[:, :, a] != 0) & (joints[:, :, b] != 0),
                joints[:, :, b] - joints[:, :, a],
                0,
            )
            for a, b in BONES
        ],
        axis=-2,
    )
    pose = np.concatenate((joints, bones), axis=-2).reshape(len(selected), 2, 72)
    pose = np.pad(pose, ((0, SEQUENCE_LENGTH - len(selected)), (0, 0), (0, 0)))
    shuttle = np.pad(shuttle, ((0, SEQUENCE_LENGTH - len(selected)), (0, 0)))
    return pose, shuttle, len(selected), selected.tolist()


def _plain(value):
    return value.model_dump() if hasattr(value, "model_dump") else value


def build_stroke_clip(video, times, player_run, shuttle_run, calibrations, frame):
    """Build one centered one-second clip, abstaining on incomplete evidence."""
    if video["mode"] != "singles":
        raise ValueError(
            "This checkpoint supports two-player singles; doubles recognition needs a dedicated model"
        )
    for run, stage in ((player_run, "players"), (shuttle_run, "shuttle")):
        if run.get("stage") != stage or run.get("video_id") != video["id"]:
            raise ValueError(
                "Recognition inputs must be same-video player and shuttle runs"
            )
    if player_run.get("stride", 1) != 1:
        raise ValueError(
            "Stroke recognition requires player tracking on every source frame"
        )
    if not 0 <= frame < len(times):
        raise ValueError("Contact frame exceeds the source video")
    result = {"frame": frame, "time_s": times[frame], "status": "abstained"}
    left, right = times[frame] - 0.5, times[frame] + 0.5
    if left < times[0] or right > video["duration_s"]:
        return result | {"reason": "Full contact context extends outside the video"}
    start, end = bisect.bisect_left(times, left), bisect.bisect_left(times, right)
    result.update(clip_start_frame=start, clip_end_frame=end)
    if any(
        run["start_frame"] > start or run["end_frame"] < end
        for run in (player_run, shuttle_run)
    ):
        return result | {
            "reason": "Track a larger window to cover half a second before and after this contact"
        }
    calibration = next(
        (
            c
            for item in calibrations
            if (c := _plain(item))["start_frame"] <= start and c["end_frame"] >= end
        ),
        None,
    )
    if calibration is None:
        return result | {
            "reason": "One court calibration must cover the full contact context"
        }
    cuts = set(player_run.get("cut_frames", [])) | set(
        shuttle_run.get("cut_frames", [])
    )
    if any(start < cut < end for cut in cuts):
        return result | {"reason": "Contact context crosses a camera cut"}
    player_rows, shuttle_rows = (
        {r["frame"]: r for r in run["frames"]} for run in (player_run, shuttle_run)
    )
    if any(
        index not in player_rows or index not in shuttle_rows
        for index in range(start, end)
    ):
        return result | {
            "reason": "Contact context contains missing tracking output frames"
        }
    if any(
        not math.isclose(float(rows[i]["time_s"]), times[i], abs_tol=2e-5)
        for rows in (player_rows, shuttle_rows)
        for i in range(start, end)
    ):
        raise ValueError("Tracking output times do not match the source timestamp map")
    if any(times[i + 1] - times[i] > 0.1 + 1e-8 for i in range(start, end - 1)):
        return result | {
            "reason": "Contact context has a source timestamp discontinuity"
        }
    corners = np.asarray(
        [
            [p["x"] * video["width"], p["y"] * video["height"]]
            for p in calibration["corners"]
        ],
        np.float32,
    )
    transform = cv2.getPerspectiveTransform(
        corners, np.asarray([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
    )
    joints, shuttles, good_pose, good_shuttle = [], [], 0, 0
    contact_tracks = None
    for index in range(start, end):
        row, observation = player_rows[index], shuttle_rows[index]
        if row.get("scene_cut") or observation.get("scene_cut"):
            return result | {"reason": "Contact context crosses a camera cut"}
        people = []
        for person in row["players"]:
            points = np.asarray(person.get("keypoints", []), np.float64)
            box = np.asarray(person.get("box", []), np.float64)
            if (
                points.shape != (17, 3)
                or box.shape != (4,)
                or not np.isfinite(points).all()
                or not np.isfinite(box).all()
            ):
                continue
            if (
                min(points[15:, 2]) < 0.3
                or np.mean(points[:, 2] >= 0.3) < 0.5
                or np.any(box[2:] <= box[:2])
            ):
                continue
            feet = cv2.perspectiveTransform(
                points[15:, :2].astype(np.float32).reshape(1, 2, 2), transform
            )[0].mean(axis=0)
            if (
                not np.isfinite(feet).all()
                or np.any(feet < -0.12)
                or np.any(feet > 1.12)
            ):
                continue
            people.append(
                (
                    float(feet[1]),
                    normalize_joints(points[:, :2], box),
                    person.get("track_id"),
                )
            )
        valid_pose = len(people) == 2
        if valid_pose:
            people.sort(key=lambda person: person[0])
            joints.append(np.stack([person[1] for person in people]))
            good_pose += 1
            if index == frame:
                contact_tracks = {"far": people[0][2], "near": people[1][2]}
        else:
            joints.append(np.zeros((2, 17, 2)))
        point = observation["shuttle"]
        visible = (
            valid_pose
            and point.get("visible")
            and not point.get("repaired", False)
            and all(
                point.get(axis) is not None and math.isfinite(point[axis])
                for axis in ("x", "y")
            )
        )
        if visible:
            shuttles.append([point["x"] / video["width"], point["y"] / video["height"]])
            good_shuttle += 1
        else:
            shuttles.append([0.0, 0.0])
    count = end - start
    result["coverage"] = {
        "source_frames": count,
        "two_player_frames": good_pose,
        "visible_shuttle_frames": good_shuttle,
        "pose_fraction": good_pose / count,
        "shuttle_fraction": good_shuttle / count,
    }
    if good_pose / count < 0.8 or good_shuttle / count < 0.5 or not contact_tracks:
        return result | {
            "reason": "Insufficient two-player pose or shuttle visibility in contact context"
        }
    pose, shuttle, length, sampled = pack_sequence(joints, shuttles)
    return result | {
        "status": "ready",
        "pose": pose,
        "shuttle": shuttle,
        "length": length,
        "sampled_frames": [start + i for i in sampled],
        "contact_tracks": contact_tracks,
    }
