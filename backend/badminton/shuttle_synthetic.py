"""Own procedural footage, independent source groups and exact generated targets."""

import hashlib

import cv2
import numpy as np
from PIL import Image, ImageDraw

WIDTH, HEIGHT, FRAMES = 512, 288, 24
SPLITS = {"train": 128, "validation": 16, "test": 16}
PARENT_SHA256 = "df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a"
PROTOCOL = {
    "schema_version": 1,
    "name": "procedural-shuttle-adaptation-v1",
    "namespace": "synthetic-shuttle-v1",
    "size": [WIDTH, HEIGHT],
    "frames_per_group": FRAMES,
    "split_groups": SPLITS,
    "sequence_length": 8,
    "checkpoint_sha256": PARENT_SHA256,
    "inventory_sha256": "273e0749d148e952ad1fb0534363b3971e2584702f834ad2084c59e632990822",
    "packet_sha256": "3b22c07a3592728b6aa17e7d7c28f0089a8820b1373ace1289796d2e99e5466d",
    "labels_sha256": "fd25029ae49891f544989cdbfa20e5077571c1048c960e2d77ddee1fe7abd158",
    "baseline_sha256": "915f678fa2b5577dff37811ba92ff9077c300eefc788fcab2873c12c2ffc6f64",
    "metrics": {"case_count": 60, "localization_tolerance_diagonal": 0.005},
    "generator": {
        "background_rgb": [20, 160],
        "pixel_noise_sd": [0, 6],
        "court_top_y": [35, 85],
        "court_bottom_y": [245, 280],
        "actors": [2, 4],
        "distractors": [2, 12],
        "actor_speed_px_per_frame": [-1.5, 1.5],
        "distractor_speed_px_per_frame": [-3, 3],
        "shuttle_radius_px": [0.6, 2.4],
        "shuttle_intensity": [150, 255],
        "shuttle_start_x": [50, 462],
        "shuttle_start_y": [40, 248],
        "shuttle_velocity_x": [-9, 9],
        "shuttle_velocity_y": [-5, 5],
        "shuttle_acceleration_y": [-0.2, 0.2],
        "blur_trail_fraction": [0, 0.8],
        "absent_group_probability": 0.15,
        "occlusion_group_probability": 0.4,
        "occlusion_start": [4, 16],
        "occlusion_length": [2, 6],
        "visibility": "entire blurred shuttle support inside image; otherwise absent",
        "background": "uint8 median of all24 generated RGB frames, not clean plate",
    },
    "training": {
        "seed": 20261025,
        "epochs": 4,
        "batch_size": 1,
        "optimizer": "AdamW",
        "learning_rate": 0.0001,
        "weight_decay": 0.0001,
        "gradient_clip_norm": 1.0,
        "precision": "CUDAfloat16 autocast, float32 parameters, GradScaler",
        "trainable": "up_block_3 convolution weights and predictor weight/bias only",
        "normalization": "eval mode; BN affine parameters and buffers frozen",
        "chunk": "8*((epoch_zero_based+group_index)%3)",
        "target_sigma_px": 1.5,
        "target_support_radius_px": 4.5,
        "loss": "0.5*mean support squared error +0.5*mean complement squared error; empty set zero",
        "selection": "minimum mean validation chunk loss, earliest epoch on ties",
    },
    "evaluation": {
        "synthetic_test": "all24 frames/group, overlapping ensemble, selected after validation only",
        "control_projection": "physical_observations_v1",
        "confidence_absolute_tolerance": 0.00001,
        "confidence_relative_tolerance": 0,
        "threshold": 0.5,
        "familiar_sources": "50 complete views,13499 rows,60 cases; diagnostics only",
    },
    "limits": {"runtime_hours": 4, "retained_bytes": 2147483648},
    "limitations": [
        "Generated geometry is procedural truth, not expert badminton supervision.",
        "Familiar source diagnostics cannot select or tune weights or establish independent accuracy.",
        "No source eligibility, installed model, application defaults or complete-reference claim changes.",
    ],
}


def group_seed(split, index):
    if split not in SPLITS or type(index) is not int or not 0 <= index < SPLITS[split]:
        raise ValueError("Unknown generated source group")
    return int.from_bytes(
        hashlib.sha256(f"synthetic-shuttle-v1/{split}/{index}".encode()).digest()[:8],
        "big",
    )


def heatmaps(labels):
    """Truncated gaussian target with independent explicit visibility support."""
    yy, xx = np.indices((HEIGHT, WIDTH))
    result = np.zeros((len(labels), HEIGHT, WIDTH), dtype=np.float32)
    for index, label in enumerate(labels):
        if label["visible"]:
            distance = (xx - label["x"]) ** 2 + (yy - label["y"]) ** 2
            result[index] = np.where(
                distance <= 4.5**2, np.exp(-distance / (2 * 1.5**2)), 0
            )
    return result


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
