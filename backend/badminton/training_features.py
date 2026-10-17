"""Join source-verified labels to published pose inputs, then cache descriptors.

These MMPose features are distinct from validated application/YOLO inputs. The
input recipe and the resulting artifact preserve that domain limitation.
"""

import hashlib
import io
import json
import re
import subprocess
import zlib
from collections import Counter
from pathlib import Path, PureWindowsPath

import numpy as np

from .config import WEIGHTS
from .datasets import pinned_source
from .stroke_features import pack_sequence
from .video import write_json

RECIPE = Path(__file__).with_name("side_training_manifest.json")


def training_recipe():
    return json.loads(RECIPE.read_text(encoding="utf-8"))


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_members(listing, destination):
    """Validate technical 7-Zip listing before any files can be extracted."""
    listing = listing.replace("\r\r\n", "\n").replace("\r\n", "\n")
    if "----------" not in listing:
        raise ValueError("Extractor did not return a technical archive listing")
    members = {}
    for block in listing.split("----------", 1)[1].split("\n\n"):
        fields = dict(
            line.split(" = ", 1) for line in block.splitlines() if " = " in line
        )
        if not fields.get("Path"):
            continue
        relative = PureWindowsPath(fields["Path"])
        if (
            relative.is_absolute()
            or relative.drive
            or ".." in relative.parts
            or any(":" in p for p in relative.parts)
            or relative.parts[0] != "dataset_npy"
        ):
            raise ValueError("Feature archive paths must remain inside dataset_npy")
        if (
            any(fields.get(key) for key in ("Symbolic Link", "Hard Link", "Copy Link"))
            or fields.get("Encrypted") == "+"
            or fields.get("Alternate Stream") == "+"
        ):
            raise ValueError(
                "Feature archive cannot contain links, streams, or encryption"
            )
        path = (Path(destination).resolve() / Path(*relative.parts)).resolve()
        if not path.is_relative_to(Path(destination).resolve()):
            raise ValueError("Feature extraction target escapes its directory")
        if fields.get("Folder") == "+":
            continue
        name = relative.as_posix()
        if relative.suffix != ".npy" or name in members:
            raise ValueError("Feature archive must contain unique NumPy files")
        size = int(fields["Size"])
        crc = fields.get("CRC", "")
        if not 0 < size <= 8 * 1024 * 1024 or not re.fullmatch("[0-9A-Fa-f]{8}", crc):
            raise ValueError("Invalid feature member size or checksum")
        members[name] = {"size": size, "crc": crc.upper()}
    if not members or sum(m["size"] for m in members.values()) > 4 * 1024**3:
        raise ValueError("Feature archive is empty or exceeds the extraction budget")
    return members


def inspect_feature_archive(archive, extractor, destination, *, recipe=None):
    recipe = recipe or training_recipe()
    if file_sha(archive) != recipe["feature_archive"]["sha256"]:
        raise ValueError("Published feature archive does not match the pinned recipe")
    result = subprocess.run(
        [str(extractor), "l", "-slt", "-sccUTF-8", str(archive)],
        capture_output=True,
        check=True,
    )
    return archive_members(result.stdout.decode("utf-8"), destination)


def load_label_index(dataset, *, recipe=None):
    recipe = recipe or training_recipe()
    root = Path(dataset)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    raw = (root / "strokes.jsonl").read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum != manifest["index_sha256"] or checksum != recipe["label_index_sha256"]:
        raise ValueError("Training labels must match the pinned normalized index")
    source = pinned_source()
    if (
        manifest["source_commit"] != source["commit"]
        or manifest["splits"] != source["splits"]
    ):
        raise ValueError("Training labels must retain the frozen original-match splits")
    rows = [json.loads(line) for line in raw.splitlines()]
    return rows, manifest


def join_feature_labels(rows, members, *, recipe=None):
    recipe = recipe or training_recipe()
    targets, excluded = [], Counter()
    seen = set()
    for row in rows:
        if (
            not row["side_eligible"]
            or not row["family_eligible"]
            or row["kind"] != "shot"
            or row["family"] not in recipe["target_families"]
        ):
            excluded["label_not_eligible_for_target_side_training"] += 1
            continue
        key = tuple(row[k] for k in ("match_id", "set_id", "rally_id", "stroke_order"))
        if key in seen:
            raise ValueError("A training stroke key must be unique")
        seen.add(key)
        split = "val" if row["split"] == "validation" else row["split"]
        if split not in ("train", "val", "test"):
            raise ValueError("Quarantined labels cannot enter side training")
        stem = "_".join(str(k) for k in key)
        possibilities = [
            (end, f"dataset_npy/{split}/{prefix}_{row['raw']['type']}/{stem}")
            for end, prefix in ((0, "Top"), (1, "Bottom"))
        ]
        found = [
            (end, path)
            for end, path in possibilities
            if path + "_joints.npy" in members and path + "_shuttle.npy" in members
        ]
        if len(found) != 1:
            excluded["missing_or_ambiguous_published_feature_key"] += 1
            continue
        court_end, branch = found[0]
        targets.append(
            {
                "record_id": row["id"],
                "match_id": row["match_id"],
                "split": row["split"],
                "family": row["family"],
                "label": recipe["labels"].index(row["side"]),
                "court_end": court_end,
                "branch": branch,
            }
        )
    return targets, dict(excluded)


def _read_array(root, relative, members):
    base = Path(root).resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Feature array path escapes the verified root")
    raw = path.read_bytes()
    entry = members[relative]
    if len(raw) != entry["size"] or f"{zlib.crc32(raw):08X}" != entry["crc"]:
        raise ValueError("Extracted feature bytes do not match the pinned archive")
    values = np.load(io.BytesIO(raw), allow_pickle=False)
    if values.dtype.kind not in "fi" or not np.isfinite(values).all():
        raise ValueError("Published features must contain finite numeric arrays")
    return values


def load_training_clip(root, target, members, *, recipe=None):
    recipe = recipe or training_recipe()
    branch = target["branch"]
    joints = _read_array(root, branch + "_joints.npy", members)
    shuttle = _read_array(root, branch + "_shuttle.npy", members)
    if (
        joints.ndim != 4
        or joints.shape[1:] != (2, 17, 2)
        or not 1 <= len(joints) <= 240
        or shuttle.shape != (len(joints), 2)
    ):
        raise ValueError(
            "Published feature shape does not match the two-player clip contract"
        )
    people = np.any(joints != 0, axis=(-1, -2)).all(axis=1)
    visible = np.any(shuttle != 0, axis=1)
    if (
        people.mean() < recipe["input_gate"]["pose_fraction"]
        or visible.mean() < recipe["input_gate"]["shuttle_fraction"]
        or not people[len(joints) // 2]
    ):
        return None
    pose, points, length, _ = pack_sequence(joints, shuttle)
    return pose, points, length


def prepare_side_descriptors(
    dataset,
    feature_root,
    members,
    output,
    progress=print,
    *,
    recipe=None,
    batch_size=64,
    report_progress=None,
):
    """Freeze BST-0, using its 300-value descriptor and the known hitter court end."""
    import torch

    from .vendor.bst.bst import BST_0

    recipe = recipe or training_recipe()
    rows, labels_manifest = load_label_index(dataset, recipe=recipe)
    targets, exclusions = join_feature_labels(rows, members, recipe=recipe)
    checkpoint = WEIGHTS / "bst_0_JnB_bone_2.pt"
    if file_sha(checkpoint) != recipe["base_checkpoint_sha256"]:
        raise ValueError("Descriptor checkpoint does not match the training recipe")
    model = BST_0(in_dim=72, seq_len=30, n_class=35)
    model.load_state_dict(
        torch.load(checkpoint, map_location="cpu", weights_only=True), strict=True
    )
    model.mlp_head = torch.nn.Identity()
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = model.to(device).eval()
    embeddings, accepted = [], []
    pending = []

    def flush(model):
        if not pending:
            return
        with torch.inference_mode():
            vectors = (
                model(
                    torch.from_numpy(np.stack([v[1][0] for v in pending])).to(device),
                    torch.from_numpy(np.stack([v[1][1] for v in pending])).to(device),
                    torch.tensor([v[1][2] for v in pending], device=device),
                )
                .cpu()
                .numpy()
            )
        ends = np.eye(2, dtype=np.float32)[[v[0]["court_end"] for v in pending]]
        embeddings.append(np.concatenate((vectors, ends), axis=1))
        accepted.extend(v[0] for v in pending)
        pending.clear()

    try:
        for number, target in enumerate(targets):
            clip = load_training_clip(feature_root, target, members, recipe=recipe)
            if clip is None:
                exclusions["published_pose_or_shuttle_input_gate"] = (
                    exclusions.get("published_pose_or_shuttle_input_gate", 0) + 1
                )
            else:
                pending.append((target, clip))
                if len(pending) >= batch_size:
                    flush(model)
            if number % 500 == 0:
                progress(f"Descriptor clips {number}/{len(targets)}")
                if report_progress:
                    report_progress(number / max(1, len(targets)))
        flush(model)
    finally:
        del model
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
    if not accepted:
        raise ValueError("No source-verified clips passed the descriptor input gates")
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    arrays = destination / "descriptors.npz"
    np.savez_compressed(
        arrays,
        features=np.concatenate(embeddings),
        labels=np.asarray([r["label"] for r in accepted], np.int64),
        matches=np.asarray([r["match_id"] for r in accepted], np.int64),
        splits=np.asarray([r["split"] for r in accepted]),
        families=np.asarray([r["family"] for r in accepted]),
        record_ids=np.asarray([r["record_id"] for r in accepted]),
    )
    metadata = {
        "schema_version": 1,
        "kind": "published_mmpose_side_descriptors",
        "device": device,
        "recipe": recipe,
        "label_index_sha256": labels_manifest["index_sha256"],
        "array_sha256": file_sha(arrays),
        "record_count": len(accepted),
        "split_counts": dict(Counter(r["split"] for r in accepted)),
        "excluded": exclusions,
        "meaning": "Known hitter court end and published MMPose inputs; this is not validated YOLO-domain inference or end-to-end accuracy",
    }
    write_json(destination / "manifest.json", metadata)
    if report_progress:
        report_progress(1)
    return metadata
