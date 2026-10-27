"""Research-only observed-component scoring; never changes installed tracking defaults."""

import copy
import math

import numpy as np

METHOD = "observed-component-logistic-v1"
FEATURE_NAMES = [
    "confidence",
    "log1p_area",
    "box_width_fraction",
    "box_height_fraction",
    "log_box_aspect",
    "box_density",
    "log1p_candidate_count",
    "previous_speed_diagonals_s",
    "next_speed_diagonals_s",
    "velocity_difference_diagonals_s",
    "previous_available",
    "next_available",
    "previous_log_area_ratio",
    "next_log_area_ratio",
]
THRESHOLDS = [i / 10 for i in range(1, 10)]
STEPS, LEARNING_RATE, L2 = 500, 0.1, 0.01
MAX_STEP_S, TOLERANCE = 0.10, 0.005


def _finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _geometry(width, height):
    if not all(_finite(v) and v > 0 for v in (width, height)):
        raise ValueError("Positive finite source geometry required")
    diagonal = math.hypot(width, height)
    if not math.isfinite(diagonal):
        raise ValueError("Finite source diagonal required")
    return diagonal


def _segments(rows, segments):
    if segments is None:
        segments = (
            [
                {
                    "start_frame": rows[0]["frame"],
                    "end_frame": rows[-1]["frame"] + 1,
                    "eligible": True,
                }
            ]
            if rows
            else []
        )
    if not isinstance(segments, list):
        raise ValueError("Explicit nonoverlapping source segments required")
    last = -1
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Invalid source segment")
        first, end = segment.get("start_frame"), segment.get("end_frame")
        if (
            type(first) is not int
            or type(end) is not int
            or not 0 <= first < end
            or first < last
            or type(segment.get("eligible")) is not bool
        ):
            raise ValueError("Ordered nonoverlapping integer source segments required")
        last = end
    result, cursor = [], 0
    for row in rows:
        frame = row["frame"]
        while cursor < len(segments) and segments[cursor]["end_frame"] <= frame:
            cursor += 1
        segment = segments[cursor] if cursor < len(segments) else None
        eligible = (
            segment is not None
            and segment["start_frame"] <= frame < segment["end_frame"]
            and segment["eligible"]
            and row.get("selection_available", True)
            and not row["shuttle"].get("selection_context_excluded", False)
        )
        camera = row.get("camera_segment_start_frame")
        if camera is not None and (type(camera) is not int or not 0 <= camera <= frame):
            raise ValueError("Invalid native camera identity")
        result.append((cursor, camera) if eligible else None)
    return result


def _validate_rows(rows, width, height):
    _geometry(width, height)
    if not isinstance(rows, list):
        raise ValueError("Complete source rows must be a list")
    previous_frame, previous_time = -1, -1.0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid source row")
        frame, timestamp = row.get("frame"), row.get("time_s")
        if (
            type(frame) is not int
            or frame <= previous_frame
            or not _finite(timestamp)
            or timestamp < 0
            or timestamp <= previous_time
        ):
            raise ValueError(
                "Unique increasing frames and finite native clocks required"
            )
        previous_frame, previous_time = frame, timestamp
        if type(row.get("selection_available", True)) is not bool:
            raise ValueError("Explicit boolean observation availability required")
        point = row.get("shuttle")
        if not isinstance(point, dict) or type(point.get("visible")) is not bool:
            raise ValueError("Explicit observation visibility required")
        if (
            "selection_context_excluded" in point
            and type(point["selection_context_excluded"]) is not bool
        ):
            raise ValueError("Invalid scene exclusion marker")
        candidates = point.get("component_candidates")
        if not isinstance(candidates, list):
            raise ValueError("Observed component candidates required")
        ids = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("Invalid observed candidate")
            identity = candidate.get("id")
            if type(identity) is not int or identity <= 0 or identity in ids:
                raise ValueError(
                    "Unique positive integral component identities required"
                )
            ids.add(identity)
            x, y, confidence = (candidate.get(k) for k in ("x", "y", "confidence"))
            box, area = (
                candidate.get("box_heatmap"),
                candidate.get("area_heatmap_pixels"),
            )
            if (
                not all(_finite(v) for v in (x, y, confidence))
                or not 0 <= x <= width
                or not 0 <= y <= height
                or not 0 <= confidence <= 1
                or not isinstance(box, (list, tuple))
                or len(box) != 4
                or any(type(v) is not int for v in box)
                or type(area) is not int
                or area <= 0
            ):
                raise ValueError(
                    "Finite bounded observed coordinates and component geometry required"
                )
            bx, by, bw, bh = box
            if not (
                0 <= bx < bx + bw <= 512
                and 0 <= by < by + bh <= 288
                and area <= bw * bh
            ):
                raise ValueError("Invalid fixed-resolution component box or area")
        if point["visible"]:
            if not all(_finite(point.get(k)) for k in ("x", "y", "confidence")):
                raise ValueError(
                    "Visible observation must retain finite coordinates/confidence"
                )
            if not 0 <= point["x"] <= width or not 0 <= point["y"] <= height:
                raise ValueError("Visible observation outside source geometry")


def feature_rows(rows, width=512, height=288, segments=None):
    """Extract label-free features; uncovered/ineligible rows supply no candidates.

    ``segments=None`` declares this complete supplied group to be one eligible
    source view. Familiar-source callers must supply their proven segment map.
    Camera tags and explicit exclusions further restrict every neighbor link.
    """
    _validate_rows(rows, width, height)
    diagonal = _geometry(width, height)
    membership = _segments(rows, segments)
    features, row_indices, identities, support = [], [], [], []
    for index, row in enumerate(rows):
        if membership[index] is None:
            continue
        candidates = row["shuttle"]["component_candidates"]
        for candidate in candidates:
            vectors, ratios, flags, used = [], [], [], [row["frame"]]
            for offset in (-1, 1):
                other_index = index + offset
                other = rows[other_index] if 0 <= other_index < len(rows) else None
                contiguous = (
                    other is not None
                    and membership[other_index] == membership[index]
                    and other["frame"] == row["frame"] + offset
                    and 0 < abs(other["time_s"] - row["time_s"]) <= MAX_STEP_S + 1e-12
                )
                choices = other["shuttle"]["component_candidates"] if contiguous else []
                if not choices:
                    vectors.append(np.zeros(2, dtype=np.float64))
                    ratios.append(0.0)
                    flags.append(0.0)
                    continue
                closest = min(
                    choices,
                    key=lambda c: (
                        math.hypot(c["x"] - candidate["x"], c["y"] - candidate["y"]),
                        c["id"],
                    ),
                )
                dt = other["time_s"] - row["time_s"]
                vectors.append(
                    np.array(
                        [closest["x"] - candidate["x"], closest["y"] - candidate["y"]],
                        dtype=np.float64,
                    )
                    / (diagonal * dt)
                )
                ratios.append(
                    math.log(
                        (candidate["area_heatmap_pixels"] + 1)
                        / (closest["area_heatmap_pixels"] + 1)
                    )
                )
                flags.append(1.0)
                used.append(other["frame"])
            area = candidate["area_heatmap_pixels"]
            _, _, bw, bh = candidate["box_heatmap"]
            values = [
                candidate["confidence"],
                math.log1p(area),
                bw / 512,
                bh / 288,
                math.log(bw / bh),
                area / (bw * bh),
                math.log1p(len(candidates)),
                float(np.linalg.norm(vectors[0])),
                float(np.linalg.norm(vectors[1])),
                float(np.linalg.norm(vectors[1] - vectors[0])) if all(flags) else 0.0,
                *flags,
                *ratios,
            ]
            if not all(math.isfinite(v) for v in values):
                raise ValueError("Native clock produces nonfinite component features")
            features.append(np.clip(values, -20, 20))
            row_indices.append(index)
            identities.append(candidate["id"])
            support.append(sorted(used))
    return {
        "features": np.asarray(features, dtype=np.float64).reshape(
            -1, len(FEATURE_NAMES)
        ),
        "row_indices": row_indices,
        "component_ids": identities,
        "support_frames": support,
        "eligible_rows": [value is not None for value in membership],
    }


def _truth(label, frame):
    if (
        not isinstance(label, dict)
        or label.get("frame") != frame
        or type(label.get("frame")) is not int
    ):
        raise ValueError("Exact native label/frame correspondence required")
    state = label.get("state")
    if state is None:
        if type(label.get("visible")) is not bool:
            raise ValueError("Explicit label visibility or unknown state required")
        state = "visible" if label["visible"] else "not_visible"
    if state not in {"visible", "not_visible", "unknown", "visible_unlocalizable"}:
        raise ValueError("Unknown truth-state encoding")
    if "visible" in label and (
        type(label["visible"]) is not bool
        or (
            state in {"visible", "not_visible"}
            and label["visible"] != (state == "visible")
        )
    ):
        raise ValueError("Conflicting truth visibility")
    if state == "visible" and not all(_finite(label.get(k)) for k in ("x", "y")):
        raise ValueError("Localizable truth requires finite coordinates")
    return state


def _group(group, width, height, split=None):
    if not isinstance(group, dict) or (
        split is not None and group.get("split") != split
    ):
        raise ValueError(f"Only explicit {split} groups are permitted")
    rows, labels = group.get("rows"), group.get("labels")
    _validate_rows(rows, width, height)
    if not isinstance(labels, list) or len(labels) != len(rows):
        raise ValueError("Complete labels and rows must retain the same denominator")
    states = [_truth(label, row["frame"]) for label, row in zip(labels, rows)]
    if any(
        state == "visible"
        and not (0 <= label["x"] <= width and 0 <= label["y"] <= height)
        for state, label in zip(states, labels)
    ):
        raise ValueError("Truth outside source geometry")
    return rows, labels, states


def _sigmoid(logits):
    return 1 / (1 + np.exp(-np.clip(logits, -30, 30)))


def fit(groups, width=512, height=288):
    """Fit the sole frozen recipe using explicit generated training groups only."""
    if not isinstance(groups, list) or not groups:
        raise ValueError("Nonempty complete training groups required")
    matrices, targets = [], []
    total_frames = eligible_frames = 0
    tolerance = TOLERANCE * _geometry(width, height)
    for group in groups:
        rows, labels, states = _group(group, width, height, "train")
        if any(state not in {"visible", "not_visible"} for state in states):
            raise ValueError(
                "Training requires explicit generated visible/negative truth"
            )
        extracted = feature_rows(rows, width, height, group.get("segments"))
        matrices.append(extracted["features"])
        total_frames += len(rows)
        eligible_frames += sum(extracted["eligible_rows"])
        for index, identity in zip(
            extracted["row_indices"], extracted["component_ids"]
        ):
            candidate = next(
                c
                for c in rows[index]["shuttle"]["component_candidates"]
                if c["id"] == identity
            )
            label = labels[index]
            targets.append(
                float(
                    states[index] == "visible"
                    and math.hypot(
                        candidate["x"] - label["x"], candidate["y"] - label["y"]
                    )
                    <= tolerance
                )
            )
    x = np.concatenate(matrices)
    y = np.asarray(targets, dtype=np.float64)
    positive, negative = int(y.sum()), int(len(y) - y.sum())
    result = {
        "schema_version": 1,
        "method": METHOD,
        "feature_names": list(FEATURE_NAMES),
        "training_groups": len(groups),
        "training_frames": total_frames,
        "training_eligible_frames": eligible_frames,
        "training_candidates": len(y),
        "positive_candidates": positive,
        "negative_candidates": negative,
        "normalization_input": "train",
        "fit_input": "train",
        "steps": STEPS,
        "learning_rate": LEARNING_RATE,
        "l2": L2,
    }
    if not positive or not negative:
        return {
            **result,
            "available": False,
            "reason": "training_requires_both_candidate_classes",
        }
    mean = x.mean(axis=0)
    scale = np.maximum(x.std(axis=0), 1e-6)
    z = (x - mean) / scale
    weights = np.zeros(len(FEATURE_NAMES), dtype=np.float64)
    intercept = 0.0
    sample_weight = np.where(y == 1, 0.5 / positive, 0.5 / negative)
    for _ in range(STEPS):
        residual = (_sigmoid(z @ weights + intercept) - y) * sample_weight
        weights -= LEARNING_RATE * (z.T @ residual + L2 * weights)
        intercept -= LEARNING_RATE * float(residual.sum())
    if not np.isfinite(weights).all() or not math.isfinite(intercept):
        raise ValueError("Scorer fitting produced nonfinite parameters")
    return {
        **result,
        "available": True,
        "reason": None,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "weights": weights.tolist(),
        "intercept": intercept,
    }


def _scorer(value):
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("method") != METHOD
        or value.get("feature_names") != FEATURE_NAMES
        or type(value.get("available")) is not bool
    ):
        raise ValueError("Invalid fixed-recipe component scorer")
    if not value["available"]:
        if not isinstance(value.get("reason"), str) or not value["reason"]:
            raise ValueError("Unavailable scorer requires an explicit reason")
        return None
    arrays = []
    for key in ("mean", "scale", "weights"):
        values = value.get(key)
        if (
            not isinstance(values, list)
            or len(values) != len(FEATURE_NAMES)
            or not all(_finite(v) for v in values)
        ):
            raise ValueError("Finite correctly shaped scorer parameters required")
        arrays.append(np.asarray(values, dtype=np.float64))
    if np.any(arrays[1] < 1e-6) or not _finite(value.get("intercept")):
        raise ValueError("Invalid scorer normalization or intercept")
    return (*arrays, value["intercept"])


def select(rows, scorer, threshold, width=512, height=288, segments=None):
    """Return separate predictions choosing only original observed candidates."""
    if not _finite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Finite probability threshold required")
    extracted = feature_rows(rows, width, height, segments)
    params = _scorer(scorer)
    available = params is not None
    probabilities = (
        _sigmoid(
            ((extracted["features"] - params[0]) / params[1]) @ params[2] + params[3]
        )
        if available
        else np.zeros(len(extracted["row_indices"]))
    )
    if not np.isfinite(probabilities).all():
        raise ValueError("Scorer produced nonfinite candidate probabilities")
    choices = {}
    for item, (index, identity) in enumerate(
        zip(extracted["row_indices"], extracted["component_ids"])
    ):
        choices.setdefault(index, []).append(
            (float(probabilities[item]), identity, extracted["support_frames"][item])
        )
    result = copy.deepcopy(rows)
    for index, row in enumerate(result):
        eligible = extracted["eligible_rows"][index]
        usable = available and eligible
        point = row["shuttle"]
        row["selection_available"] = usable
        if usable:
            reason = None
        elif not rows[index].get("selection_available", True):
            reason = (
                rows[index].get("selection_unavailable_reason")
                or "original_input_unavailable"
            )
        elif not available:
            reason = scorer["reason"]
        else:
            reason = "unverified_or_excluded_source_context"
        row["selection_unavailable_reason"] = reason
        point.update(
            visible=False,
            x=None,
            y=None,
            selected_component_id=None,
            selection_method=METHOD,
            selection_probability=None,
            repaired=False,
            selection_reason="unavailable" if not usable else "no_observed_component",
            selection_context_frames=[row["frame"]],
            selection_context_start_frame=row["frame"],
            selection_context_end_frame=row["frame"] + 1,
        )
        if not usable or not choices.get(index):
            continue
        probability, identity, support = min(
            choices[index], key=lambda v: (-v[0], v[1])
        )
        point.update(
            selection_probability=probability,
            selection_reason="below_scorer_threshold",
            selection_context_frames=support,
            selection_context_start_frame=min(support),
            selection_context_end_frame=max(support) + 1,
        )
        if probability >= threshold:
            candidate = next(
                c for c in point["component_candidates"] if c["id"] == identity
            )
            point.update(
                visible=True,
                x=candidate["x"],
                y=candidate["y"],
                confidence=candidate["confidence"],
                selected_component_id=identity,
                selection_reason="highest_component_probability",
            )
    return result


def _f1(tp, fp, fn):
    denominator = 2 * tp + fp + fn
    return 2 * tp / denominator if denominator else None


def metrics(groups, width=512, height=288):
    """Retain complete denominators and distinguish unknown/unavailable inputs."""
    if not isinstance(groups, list):
        raise ValueError("Complete evaluation groups required")
    counts = dict.fromkeys(
        [
            "frames",
            "visible",
            "negative",
            "unknown",
            "visible_unlocalizable",
            "unavailable",
            "unavailable_visible",
            "unavailable_negative",
            "visibility_tp",
            "visibility_fp",
            "visibility_fn",
            "visibility_tn",
            "localization_tp",
            "localization_fp",
            "localization_fn",
            "localization_tn",
            "displaced",
            "component_agrees",
        ],
        0,
    )
    errors, outcomes = [], []
    tolerance = TOLERANCE * _geometry(width, height)
    for group_index, group in enumerate(groups):
        rows, labels, states = _group(group, width, height)
        for row, label, state in zip(rows, labels, states):
            point = row["shuttle"]
            available = row.get("selection_available", True)
            if type(available) is not bool:
                raise ValueError("Explicit observation availability required")
            counts["frames"] += 1
            counts[
                {
                    "visible": "visible",
                    "not_visible": "negative",
                    "unknown": "unknown",
                    "visible_unlocalizable": "visible_unlocalizable",
                }[state]
            ] += 1
            counts["unavailable"] += not available
            outcome = {
                "group": group.get("index", group_index),
                "frame": row["frame"],
                "state": state,
                "available": available,
            }
            if state == "unknown":
                outcome.update(visibility="unscored", localization="unscored")
                outcomes.append(outcome)
                continue
            visible = state in {"visible", "visible_unlocalizable"}
            observed = available and point["visible"]
            if not available:
                counts[
                    "unavailable_visible" if visible else "unavailable_negative"
                ] += 1
            visibility = (
                ("tp" if observed else "fn")
                if visible
                else ("fp" if observed else "tn" if available else "unavailable")
            )
            if visibility != "unavailable":
                counts["visibility_" + visibility] += 1
            localization = "unscored"
            if state == "visible":
                counts["component_agrees"] += any(
                    math.hypot(c["x"] - label["x"], c["y"] - label["y"]) <= tolerance
                    for c in point["component_candidates"]
                )
                if observed:
                    error = math.hypot(point["x"] - label["x"], point["y"] - label["y"])
                    errors.append(error)
                    if error <= tolerance:
                        counts["localization_tp"] += 1
                        localization = "tp"
                    else:
                        counts["localization_fp"] += 1
                        counts["localization_fn"] += 1
                        counts["displaced"] += 1
                        localization = "displaced"
                else:
                    counts["localization_fn"] += 1
                    localization = "fn"
            elif state == "not_visible":
                localization = (
                    "fp" if observed else "tn" if available else "unavailable"
                )
                if localization != "unavailable":
                    counts["localization_" + localization] += 1
            outcome.update(visibility=visibility, localization=localization)
            outcomes.append(outcome)
    return {
        **counts,
        "mean_error_predicted_visible_px": float(np.mean(errors)) if errors else None,
        "localization_f1": _f1(
            counts["localization_tp"],
            counts["localization_fp"],
            counts["localization_fn"],
        ),
        "visibility_f1": _f1(
            counts["visibility_tp"], counts["visibility_fp"], counts["visibility_fn"]
        ),
        "outcomes": outcomes,
    }


def choose_threshold(groups, scorer, width=512, height=288):
    """Choose the frozen grid using validation only; never changes fitted weights."""
    if not isinstance(groups, list) or not groups:
        raise ValueError("Nonempty validation groups required")
    for group in groups:
        _group(group, width, height, "validation")
    available = _scorer(scorer) is not None
    grid = []
    for threshold in THRESHOLDS if available else [0.5]:
        predicted = [
            {
                **group,
                "rows": select(
                    group["rows"],
                    scorer,
                    threshold,
                    width,
                    height,
                    group.get("segments"),
                ),
            }
            for group in groups
        ]
        grid.append(
            {"threshold": threshold, "metrics": metrics(predicted, width, height)}
        )
    if not available:
        return {
            "available": False,
            "reason": scorer["reason"],
            "threshold": None,
            "metrics": grid[0]["metrics"],
            "grid": [],
        }
    supported = sum(
        item["available"] and item["state"] in {"visible", "not_visible"}
        for item in grid[0]["metrics"]["outcomes"]
    )
    if not supported:
        return {
            "available": False,
            "reason": "validation_has_no_available_localization_truth",
            "threshold": None,
            "metrics": grid[0]["metrics"],
            "grid": grid,
        }
    # With no positive truth or predictions, reported F1 remains undefined.
    # For threshold ordering only it ties a zero F1, so false detections cannot
    # beat an otherwise empty outcome; the declared FP/threshold ties decide.
    best = max(
        grid,
        key=lambda row: (
            row["metrics"]["localization_f1"]
            if row["metrics"]["localization_f1"] is not None
            else 0,
            -row["metrics"]["localization_fp"],
            row["threshold"],
        ),
    )
    return {
        "available": True,
        "reason": None,
        "threshold": best["threshold"],
        "metrics": best["metrics"],
        "grid": grid,
        "selection_input": "validation",
    }
