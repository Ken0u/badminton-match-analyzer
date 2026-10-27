"""Owned procedural groups with a fresh, independent selection-study namespace."""

import hashlib

import cv2
import numpy as np
from PIL import Image, ImageDraw

WIDTH, HEIGHT, FRAMES = 512, 288, 24
SPLITS = {"train": 128, "validation": 16, "test": 32}
NAMESPACE = "synthetic-shuttle-selection-v1"
PROTOCOL = {
    "schema_version": 1,
    "name": "shuttle-component-selection-v1",
    "task_id": 330,
    "frozen_spec_sha256": "d3e9b76089a07fd04433d8e322e4f7163a0d6960f282a99010ab02e8e986bed4",
    "namespace": "synthetic-shuttle-selection-v1",
    "input_size": [512, 288],
    "frames_per_group": 24,
    "source_fps": 30,
    "sequence_length": 8,
    "split_groups": {"train": 128, "validation": 16, "test": 32},
    "generator": "Owned #311 procedural geometry, byte-identical generate_group body; "
    "independently versioned namespace/seeds only. Full-source uint8 median "
    "background.",
    "input_artifacts": {
        "parent-checkpoint": {
            "path": "models/weights/TrackNet_best.pt",
            "sha256": "df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a",
        },
        "decoder-checkpoint": {
            "path": ".cache/capacity311-experiment-v1/decoder/epoch-4.pt",
            "sha256": "1506668b947a90f2d3cff79ef23a480aa97c9aed1a802fcffec9df6e8bb42598",
        },
        "convolution-checkpoint": {
            "path": ".cache/capacity311-experiment-v1/convolution/epoch-4.pt",
            "sha256": "2c65087f1849bc0a22740aa48c252b5cfd92a175693f08f18350c639082d4833",
        },
        "decoder-selection": {
            "path": ".cache/capacity311-experiment-v1/decoder/selection.json",
            "sha256": "60dfcab0bfc3d9bb524b4ac53a5bb1b3d63bdcc835751e5b5d055149f9f08d0d",
        },
        "convolution-selection": {
            "path": ".cache/capacity311-experiment-v1/convolution/selection.json",
            "sha256": "acf50a4e63fef72310145650593e5eb136f9d6c023a944fe156499cffe0533db",
        },
        "capacity-experiment": {
            "path": ".cache/capacity311-experiment-v1/experiment.json",
            "sha256": "780374cc379534d853680bafa0159bcad7d6ee5783f942a616a9dd00a40d40f3",
        },
        "capacity-raw-index": {
            "path": ".cache/capacity313-experiment-v1/raw-index.json",
            "sha256": "a0a383d3df756f0095d0025b414385d8294aa77df5fb286d69a174d377daa4df",
        },
        "capacity-continuation-experiment": {
            "path": ".cache/capacity313-experiment-v1/experiment.json",
            "sha256": "c15ae687689784f4bd9d05bcbd3747b89286925c861298db7f09c090657c39e5",
        },
        "capacity-continuation-completion": {
            "path": ".cache/capacity313-completion-v1.json",
            "sha256": "1bfbdf4d148a6086a08bc49c175c86f5afeb2c83726f6489d5e66f3fc9b316c1",
        },
        "familiar-source-inventory": {
            "path": ".cache/shuttle65-source-inventory.json",
            "sha256": "273e0749d148e952ad1fb0534363b3971e2584702f834ad2084c59e632990822",
        },
        "familiar-source-packet": {
            "path": ".cache/shuttle139-packet-v1/packet.json",
            "sha256": "3b22c07a3592728b6aa17e7d7c28f0089a8820b1373ace1289796d2e99e5466d",
        },
        "familiar-source-labels": {
            "path": ".cache/shuttle139-labels-v1/labels.json",
            "sha256": "fd25029ae49891f544989cdbfa20e5077571c1048c960e2d77ddee1fe7abd158",
        },
        "familiar-source-baseline": {
            "path": ".cache/shuttle139-baseline-v2/baseline.json",
            "sha256": "915f678fa2b5577dff37811ba92ff9077c300eefc788fcab2873c12c2ffc6f64",
        },
    },
    "variants": ["control", "decoder", "convolution"],
    "neural": {
        "precision": "CUDA float16",
        "heatmap_threshold": 0.5,
        "weights_updated": False,
        "overlapping_ensemble": True,
    },
    "features": {
        "names": [
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
        ],
        "clip": [-20, 20],
        "maximum_adjacent_step_s": 0.1,
        "nearest_tie": "component ID",
        "missing_neighbors": "zero numeric values and explicit availability flags",
        "source_support": "Adjacent native frames only, within same eligible "
        "camera/scene segment; no interpolation, extrapolation "
        "or invented coordinates.",
    },
    "fit": {
        "normalization": "training mean/std only",
        "std_floor": 1e-06,
        "steps": 500,
        "learning_rate": 0.1,
        "l2": 0.01,
        "penalize_intercept": False,
        "initialization": "zeros",
        "class_balance": "half positive and half negative total sample weight",
        "sigmoid_logit_clip": [-30, 30],
        "positive_tolerance_diagonal": 0.005,
        "missing_class": "explicitly unavailable",
    },
    "selection": {
        "thresholds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "threshold_source": "validation only",
        "threshold_order": [
            "maximum localization F1",
            "fewest localization false positives",
            "highest threshold",
        ],
        "candidate_tie": "component ID",
        "coordinates": "unchanged observed candidate",
        "probability": "separate from original observed confidence",
        "undefined_f1_comparison_rank": 0,
        "undefined_f1_reporting": "null when TP+FP+FN is zero; rank zero only "
        "for threshold comparison, retaining support "
        "counts; no available validation frames means "
        "unavailable selection",
    },
    "test": {
        "groups": 32,
        "frames": 768,
        "opens": 1,
        "requires": "All three fit/threshold receipts publicly sealed before test "
        "generation; unavailable method receipts retained.",
        "comparisons": "Unchanged selector vs corresponding fitted scorer for all "
        "three unchanged checkpoints. No winner selection or tuning.",
    },
    "familiar": {
        "raw_output_root": ".cache/capacity313-experiment-v1",
        "views_per_method": 50,
        "rows_per_method": 13499,
        "cases": 60,
        "truth_states": {"visible": 25, "not_visible": 7, "unknown": 28},
        "localization_tolerance_diagonal": 0.005,
        "baseline_localization_tp": {"control": 14, "decoder": 16, "convolution": 9},
        "new_native_inference": False,
        "use": "development diagnostic only; retain unknown/unavailable, context "
        "and all four false eligibility flags",
        "baseline_visibility_counts": {
            "control": {"tp": 15, "fp": 3, "fn": 10, "tn": 4},
            "decoder": {"tp": 17, "fp": 4, "fn": 8, "tn": 3},
            "convolution": {"tp": 23, "fp": 6, "fn": 2, "tn": 1},
        },
        "baseline_localization_counts": {
            "control": {"tp": 14, "fp": 4, "fn": 11, "tn": 4},
            "decoder": {"tp": 16, "fp": 5, "fn": 9, "tn": 3},
            "convolution": {"tp": 9, "fp": 20, "fn": 16, "tn": 1},
        },
        "baseline_agreeing_components": {
            "control": 14,
            "decoder": 16,
            "convolution": 17,
        },
    },
    "limits": {
        "runtime_hours": 12,
        "new_retained_bytes": 4294967296,
        "repair_rounds": 3,
        "paid_services": False,
    },
    "limitations": [
        "Procedural geometry is not independent real badminton truth.",
        "No neural checkpoint/default promotion or real-media training.",
        "Previously consumed #305/#311/#63 tests remain closed.",
        "No new image transfer, assessor, source/weight acquisition or source "
        "eligibility change.",
        "Complete scientific references remain 0/2; full-match accuracy "
        "remains unproven.",
    ],
}


def group_seed(split, index):
    if split not in SPLITS or type(index) is not int or not 0 <= index < SPLITS[split]:
        raise ValueError("Unknown generated selection source group")
    return int.from_bytes(
        hashlib.sha256(f"{NAMESPACE}/{split}/{index}".encode()).digest()[:8], "big"
    )


def generate_group(split, index):
    """Generate one complete independent RGB source; no filesystem/media input."""
    rng = np.random.default_rng(group_seed(split, index))
    color = rng.integers(20, 161, 3)
    noise = rng.normal(0, rng.uniform(0, 6), (HEIGHT, WIDTH, 3))
    plate = np.clip(color + noise, 0, 255).astype(np.uint8)
    top, bottom = int(rng.integers(35, 86)), int(rng.integers(245, 281))
    court = Image.fromarray(plate)
    draw = ImageDraw.Draw(court)
    vertices = [(170, top), (342, top), (485, bottom), (27, bottom)]
    draw.line([*vertices, vertices[0]], fill=(210, 210, 210), width=1)
    for fraction in (0.25, 0.5, 0.75):
        y = round(top + fraction * (bottom - top))
        half = round(86 + 143 * fraction)
        draw.line((256 - half, y, 256 + half, y), fill=(195, 195, 195), width=1)
    draw.line((256, top, 256, bottom), fill=(195, 195, 195), width=1)
    actors = []
    for _ in range(int(rng.integers(2, 5))):
        actors.append(
            (
                rng.uniform(70, 442),
                rng.uniform(80, 245),
                rng.uniform(-1.5, 1.5),
                tuple(int(c) for c in rng.integers(30, 241, 3)),
            )
        )
    distractors = [
        (rng.uniform(5, 507), rng.uniform(5, 283), rng.uniform(-3, 3))
        for _ in range(int(rng.integers(2, 13)))
    ]
    x0, y0 = rng.uniform(50, 462), rng.uniform(40, 248)
    vx, vy, ay = rng.uniform(-9, 9), rng.uniform(-5, 5), rng.uniform(-0.2, 0.2)
    radius, intensity = rng.uniform(0.6, 2.4), int(rng.integers(150, 256))
    trail = rng.uniform(0, 0.8)
    absent = rng.random() < 0.15
    occluded = rng.random() < 0.4
    occlusion_start = int(rng.integers(4, 17))
    occlusion_end = occlusion_start + int(rng.integers(2, 7))
    frames, labels = [], []
    for frame in range(FRAMES):
        image = court.copy()
        draw = ImageDraw.Draw(image)
        for ax, by, speed, rgb in actors:
            ax += speed * frame
            draw.ellipse((ax - 4, by - 24, ax + 4, by - 16), fill=rgb)
            draw.rectangle((ax - 7, by - 16, ax + 7, by), fill=rgb)
            draw.line((ax, by, ax - 6, by + 13), fill=rgb, width=3)
            draw.line((ax, by, ax + 6, by + 13), fill=rgb, width=3)
            draw.ellipse((ax + 10, by - 22, ax + 17, by - 12), outline=(225,) * 3)
        for dx, dy, speed in distractors:
            dx = (dx + frame * speed) % WIDTH
            draw.ellipse((dx - 1, dy - 1, dx + 1, dy + 1), fill=(235,) * 3)
        x, y = x0 + vx * frame, y0 + vy * frame + 0.5 * ay * frame**2
        tail_x, tail_y = x - trail * vx, y - trail * (vy + ay * frame)
        visible = (
            not absent
            and not (occluded and occlusion_start <= frame < occlusion_end)
            and radius <= min(x, tail_x)
            and max(x, tail_x) < WIDTH - radius
            and radius <= min(y, tail_y)
            and max(y, tail_y) < HEIGHT - radius
        )
        pixels = np.asarray(image).copy()
        if visible:
            # Subpixel rasterization preserves the generated trajectory center.
            mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
            center, tail = (
                (np.array([x, y]) * 16).round().astype(int),
                (np.array([tail_x, tail_y]) * 16).round().astype(int),
            )
            cv2.line(
                mask,
                tuple(center),
                tuple(tail),
                255,
                max(1, round(radius * 2)),
                lineType=cv2.LINE_AA,
                shift=4,
            )
            cv2.circle(mask, tuple(center), round(radius * 16), 255, -1, cv2.LINE_AA, 4)
            alpha = mask.astype(np.float32)[..., None] / 255
            pixels = np.clip(pixels * (1 - alpha) + intensity * alpha, 0, 255).astype(
                np.uint8
            )
        labels.append(
            {
                "frame": frame,
                "visible": bool(visible),
                "x": float(x) if visible else None,
                "y": float(y) if visible else None,
                "occluded": bool(occluded and occlusion_start <= frame < occlusion_end),
                "absent_group": bool(absent),
            }
        )
        frames.append(pixels)
    frames = np.stack(frames)
    background = np.median(frames, axis=0).astype(np.uint8)
    return frames, background, labels
