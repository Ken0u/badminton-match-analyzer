"""Source-clock visual inputs for the experimental temporal event learner.

No annotation, court calibration, trajectory or hitter coordinate enters an
encoder input. Torch is optional and imported before opening threaded media.
"""

import hashlib
import io
import json
import math
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np

from .av_runtime import open_media
from .orientation import frame_rotation, orient_frame
from .segments import METHOD, RECIPE, BoundaryDetector
from .video import SourceChangedError, write_json

MANIFEST = Path(__file__).with_name("visual_learning_manifest.json")
GROUPS = Path(__file__).with_name("aicup_capture_groups_v1.json")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_protocol(index):
    """Reject changed sources or partial/overlapping capture group assignments."""
    spec = json.loads(MANIFEST.read_text(encoding="utf-8"))
    groups = json.loads(GROUPS.read_text(encoding="utf-8"))
    for filename, key in [
        ("clips.json", "source_clip_index_sha256"),
        ("records.json", "source_records_sha256"),
    ]:
        if sha256(index / filename) != groups[key]:
            raise ValueError(f"Visual learning source index changed: {filename}")
    clips = json.loads((index / "clips.json").read_text(encoding="utf-8"))
    folds = {}
    group_ids = set()
    for group in groups["source_groups"]:
        if group["id"] in group_ids or group["fold"] not in (
            "train",
            "validation",
            "test",
        ):
            raise ValueError("Invalid or repeated capture group")
        group_ids.add(group["id"])
        for key in group["members"]:
            if key in folds:
                raise ValueError("A source clip occurs in multiple capture groups")
            folds[key] = group["fold"]
    keys = [clip_key(c) for c in clips]
    if len(set(keys)) != len(keys) or set(keys) != set(folds):
        raise ValueError("Capture groups must cover every source clip exactly once")
    # Byte duplicates must not cross folds even if the metadata calls them
    # separate clips. More subtle source overlaps require the source audit.
    media_folds = {}
    for clip in clips:
        fold = folds[clip_key(clip)]
        previous = media_folds.setdefault(clip["media_sha256"], fold)
        if previous != fold:
            raise ValueError("Identical source media crosses learning folds")
    return spec, groups, clips, folds


def clip_key(clip):
    return f"{clip['source_partition']}:{clip['source_clip_id']}"


def letterbox_rgb(rgb, spec):
    """Float32 CHW; padding normalizes to zero, with no content cropping."""
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Encoder requires an RGB uint8 image")
    height, width = rgb.shape[:2]
    target_w, target_h = spec["input_width"], spec["input_height"]
    scale = min(target_w / width, target_h / height)
    new_w, new_h = max(1, round(width * scale)), max(1, round(height * scale))
    resized = (
        cv2.resize(
            rgb,
            (new_w, new_h),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
        ).astype(np.float32)
        / 255
    )
    mean = np.asarray(spec["normalization_mean"], dtype=np.float32)
    std = np.asarray(spec["normalization_std"], dtype=np.float32)
    image = np.empty((target_h, target_w, 3), dtype=np.float32)
    image[:] = mean
    left, top = (target_w - new_w) // 2, (target_h - new_h) // 2
    image[top : top + new_h, left : left + new_w] = resized
    return np.ascontiguousarray(((image - mean) / std).transpose(2, 0, 1))


def context_indices(times, cuts, spec):
    """Nearest *observed* samples in the same uninterrupted source context.

    Returns [source center, temporal bin] indices (-1 unavailable), plus valid
    centers with enough observations on each flank. No label enters selection.
    """
    times = np.asarray(times, dtype=np.float64)
    if times.ndim != 1 or not len(times) or not np.isfinite(times).all():
        raise ValueError("Visual context requires finite source timestamps")
    if np.any(np.diff(times) <= 0):
        raise ValueError("Source timestamps must increase strictly")
    cuts = np.asarray(cuts, dtype=np.int64)
    if cuts.ndim != 1 or np.any(cuts <= 0) or np.any(cuts >= len(times)):
        raise ValueError("Camera cuts must be internal source frame indices")
    gaps = np.flatnonzero(np.diff(times) > spec["max_source_step_s"] + 1e-8) + 1
    boundaries = np.unique(np.r_[cuts, gaps])
    segments = np.searchsorted(boundaries, np.arange(len(times)), side="right")
    offsets = np.asarray(spec["offsets_s"], dtype=np.float64)
    target = times[:, None] + offsets
    right = np.searchsorted(times, target).clip(0, len(times) - 1)
    left = (right - 1).clip(0, len(times) - 1)
    # Stable ties choose the earlier actual sample.
    nearest = np.where(
        abs(times[left] - target) <= abs(times[right] - target), left, right
    )
    available = (
        (abs(times[nearest] - target) <= spec["max_sample_error_s"] + 1e-8)
        & (segments[nearest] == segments[:, None])
        & (target >= times[0] - 1e-8)
        & (target <= times[-1] + 1e-8)
    )
    nearest = np.where(available, nearest, -1)
    minimum = spec["minimum_observations_per_flank"]
    # Count distinct frames, not repeated nearest-neighbor bins on low-rate media.
    valid = np.asarray(
        [
            len(set(row[offsets < 0]) - {-1, center}) >= minimum
            and len(set(row[offsets > 0]) - {-1, center}) >= minimum
            for center, row in enumerate(nearest)
        ]
    )
    return nearest, valid


class FrozenEncoder:
    def __init__(self, weights, spec, device):
        # Must happen before threaded PyAV decode: torchvision can install an
        # FFmpeg Python log callback. open_media restores native callbacks.
        import torch
        import torchvision

        if sha256(weights) != spec["weights_sha256"]:
            raise ValueError("Generic encoder checkpoint hash mismatch")
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise ValueError("CUDA encoder requested but CUDA is unavailable")
        self.torch, self.device = torch, device
        model = torchvision.models.mobilenet_v3_small(weights=None)
        model.load_state_dict(
            torch.load(weights, map_location="cpu", weights_only=True), strict=True
        )
        self.model = model.features.eval().requires_grad_(False).to(device)
        self.runtime = {
            "torch": torch.__version__,
            "torchvision": torchvision.__version__,
            "device": device,
            "cuda": torch.version.cuda,
            "precision": "float16" if device.startswith("cuda") else "float32",
        }

    def encode(self, images, mirror=False):
        torch = self.torch
        with (
            torch.inference_mode(),
            torch.autocast(
                device_type="cuda",
                enabled=self.device.startswith("cuda"),
                dtype=torch.float16,
            ),
        ):
            inputs = torch.from_numpy(np.stack(images)).to(self.device)
            if mirror:
                inputs = inputs.flip(-1)
            outputs = torch.nn.functional.adaptive_avg_pool2d(
                self.model(inputs), (2, 2)
            )
            return outputs.flatten(1).cpu().numpy().astype(np.float16)


def feature_recipe(spec):
    return {
        "encoder": spec["encoder"],
        "camera_method": METHOD,
        "camera_recipe": RECIPE,
        "implementation": {
            name: sha256(Path(__file__).with_name(name))
            for name in (
                "visual_inputs.py",
                "segments.py",
                "orientation.py",
                "av_runtime.py",
            )
        },
    }


def read_features(directory, clip, recipe, mirror, *, verify=True):
    """A receipt is committed last. Partial/stale/corrupted caches never resume."""
    receipt_path = directory / "receipt.json"
    if not receipt_path.is_file():
        return None
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        receipt.get("recipe") != recipe
        or receipt.get("source_sha256") != clip["media_sha256"]
        or receipt.get("mirrored") != mirror
    ):
        raise ValueError(f"Incompatible visual cache: {directory}")
    arrays = {}
    for name, digest in receipt["arrays"].items():
        path = directory / name
        if verify and sha256(path) != digest:
            raise ValueError(f"Corrupted visual feature array: {path}")
        arrays[name] = np.load(path, mmap_mode="r", allow_pickle=False)
    count = receipt["frames"]
    if (
        arrays["features.npy"].shape != (count, recipe["encoder"]["feature_dim"])
        or arrays["times.npy"].shape != (count,)
        or (mirror and arrays["mirrored.npy"].shape != arrays["features.npy"].shape)
    ):
        raise ValueError("Visual feature cache has inconsistent dimensions")
    return receipt, arrays


def _save_array(path, array):
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        np.save(stream, array, allow_pickle=False)
    temporary.replace(path)


def encode_clip(raw, directory, clip, spec, recipe, encoder, mirror, batch_size):
    if hashlib.sha256(raw).hexdigest() != clip["media_sha256"]:
        raise SourceChangedError("AI CUP member source hash mismatch")
    times, cuts, images, features, mirrored = [], {}, [], [], []

    def flush():
        if images:
            features.append(encoder.encode(images))
            if mirror:
                mirrored.append(encoder.encode(images, mirror=True))
            images.clear()

    began = time.perf_counter()
    with open_media(io.BytesIO(raw)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        rotation, detector, origin = None, None, None
        for index, frame in enumerate(container.decode(stream)):
            if frame.pts is None:
                raise SourceChangedError(
                    "Visual learning requires every source frame to have PTS"
                )
            absolute = float(frame.pts * frame.time_base)
            if not math.isfinite(absolute):
                raise SourceChangedError("Nonfinite source PTS")
            if origin is None:
                origin, rotation = absolute, frame_rotation(frame)
            display = orient_frame(frame, expected_rotation=rotation)
            if detector is None:
                detector = BoundaryDetector(
                    float(stream.average_rate), display.width, display.height
                )
                dimensions = (display.width, display.height)
            if (display.width, display.height) != dimensions:
                raise SourceChangedError(
                    "Source display dimensions changed during decode"
                )
            timestamp = absolute - origin
            cuts.update(detector.process(index, timestamp, display))
            times.append(timestamp)
            images.append(
                letterbox_rgb(display.to_ndarray(format="rgb24"), spec["encoder"])
            )
            if len(images) == batch_size:
                flush()
        flush()
        if not times or (stream.frames and len(times) != stream.frames):
            raise SourceChangedError("Visual encoder did not decode every source frame")
    arrays = {
        "features.npy": np.concatenate(features),
        "times.npy": np.asarray(times, np.float64),
    }
    if mirror:
        arrays["mirrored.npy"] = np.concatenate(mirrored)
    if any(not np.isfinite(array).all() for array in arrays.values()):
        raise ValueError("Nonfinite source visual features")
    directory.mkdir(parents=True, exist_ok=True)
    for name, array in arrays.items():
        _save_array(directory / name, array)
    receipt = {
        "schema_version": 1,
        "source_sha256": clip["media_sha256"],
        "clip": clip_key(clip),
        "recipe": recipe,
        "runtime": encoder.runtime,
        "mirrored": mirror,
        "frames": len(times),
        "source_start_s": origin,
        "rotation": rotation,
        "display_dimensions": dimensions,
        "cuts": [
            {"frame": i, "time_s": times[i], "reason": reason}
            for i, reason in sorted(cuts.items())
        ],
        "arrays": {name: sha256(directory / name) for name in arrays},
        "elapsed_s": round(time.perf_counter() - began, 3),
        "annotation_inputs": False,
    }
    write_json(directory / "receipt.json", receipt)
    return receipt


def prepare_features(
    archive, index, weights, output, progress, *, device="cuda:0", batch_size=32
):
    if batch_size < 1:
        raise ValueError("Encoder batch size must be positive")
    spec, groups, clips, folds = load_protocol(index)
    if sha256(archive) != groups["source_archive_sha256"]:
        raise ValueError("AI CUP source archive hash mismatch")
    # Public val clips have no labels: retain their group membership but do not
    # extract/use them for this supervised experiment or normalization.
    labelled = [c for c in clips if c["source_partition"] == "train"]
    recipe = feature_recipe(spec)
    receipts, encoder = [], None
    output.mkdir(parents=True, exist_ok=True)
    began = time.perf_counter()
    with zipfile.ZipFile(archive) as source:
        for number, clip in enumerate(labelled):
            key = clip_key(clip)
            directory = output / key.replace(":", "-")
            mirror = folds[key] == "train"
            cached = read_features(directory, clip, recipe, mirror)
            if cached is None:
                if encoder is None:
                    encoder = FrozenEncoder(weights, spec["encoder"], device)
                receipt = encode_clip(
                    source.read(clip["media_path"]),
                    directory,
                    clip,
                    spec,
                    recipe,
                    encoder,
                    mirror,
                    batch_size,
                )
            else:
                receipt = cached[0]
            receipts.append(
                {
                    "clip": key,
                    "fold": folds[key],
                    "frames": receipt["frames"],
                    "receipt_sha256": sha256(directory / "receipt.json"),
                }
            )
            progress((number + 1) / len(labelled))
    result = {
        "clips": len(receipts),
        "frames": sum(r["frames"] for r in receipts),
        "members": receipts,
        "recipe": recipe,
        "capture_manifest_sha256": sha256(GROUPS),
        "learning_manifest_sha256": sha256(MANIFEST),
        "elapsed_s": round(time.perf_counter() - began, 3),
        "app_annotations_written": False,
    }
    write_json(output / "completed.json", result)
    return {
        key: value for key, value in result.items() if key not in ("members", "recipe")
    }
