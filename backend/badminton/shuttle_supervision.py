"""Preserve published coordinate supervision and prove native source alignment.

This importer never trains, runs models, or changes application annotations.
Publisher labels, native observations and eligibility decisions remain distinct.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import itertools
import json
import math
import os
import platform
import re
import sqlite3
import stat
import sys
import time
import unicodedata
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from uuid import uuid4

import psutil

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "data/manifests/shuttle_supervision_sources_v1.json"
)
ARCHIVE_SHA = "f87ccd54318e2e6366f2e820ba8dc1a04203c132582fc664867f0d1029bef465"
DECLARATION_SHA = "1536d95d96032414ac72a3635c9ff5a40dfbc7e8da1f513de59be7cffd0c1b9b"
ARCHIVE_URL = "https://github.com/AnInsomniacy/tracknet-series-pytorch/releases/download/dataset-v1.0.0/Shuttlecock-Trajectory-Dataset.zip"
NAMESPACES = {
    "profession_dataset": "professional",
    "professional": "professional",
    "amateur_dataset": "amateur",
    "amateur": "amateur",
    "test_dataset": "test",
    "test": "test",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite JSON number")

    return json.loads(
        Path(path).read_bytes(), object_pairs_hook=pairs, parse_constant=constant
    )


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            result.update(chunk)
    return result.hexdigest()


def contained(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Research path escapes its declared root")
    return path


def publish_stream(
    path, stream, *, limit, expected_bytes=None, expected_sha=None, progress=None
):
    """Flush then atomically publish without replacement; preserve partial evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    pending = path.with_name(path.name + ".pending-" + uuid4().hex)
    size, checksum = 0, hashlib.sha256()
    with pending.open("xb") as destination:
        while chunk := stream.read(min(1024**2, limit - size + 1)):
            size += len(chunk)
            if size > limit:
                raise ValueError("Input exceeds its declared byte bound")
            destination.write(chunk)
            checksum.update(chunk)
            if progress:
                progress(size)
        destination.flush()
        os.fsync(destination.fileno())
    if expected_bytes is not None and size != expected_bytes:
        raise ValueError("Input byte count changed")
    if expected_sha is not None and checksum.hexdigest() != expected_sha:
        raise ValueError("Input SHA256 changed")
    os.link(pending, path)
    pending.unlink()
    return {"bytes": size, "sha256": checksum.hexdigest()}


def publish_json(path, value):
    raw = encoded(value)
    return publish_stream(
        path, io.BytesIO(raw), limit=len(raw), expected_bytes=len(raw)
    )


def load_manifest(path=MANIFEST):
    spec = read_json(path)
    if (
        spec["schema_version"] != 1
        or spec["archive"]["sha256"] != ARCHIVE_SHA
        or spec["archive"]["bytes"] != 1731120724
        or spec["archive"]["url"] != ARCHIVE_URL
        or spec["source_declaration_sha256"] != DECLARATION_SHA
        or spec["csv_columns"] != ["Frame", "Visibility", "X", "Y"]
        or any(
            spec["eligibility"][key] is not False
            for key in (
                "training_allowed",
                "model_deployment_allowed",
                "dataset_redistribution_allowed",
                "independent_test_allowed",
            )
        )
    ):
        raise ValueError("Changed frozen source or usage eligibility")
    for value in spec["limits"].values():
        if type(value) is not int or value <= 0:
            raise ValueError("Invalid source preparation bound")
    return spec


def verify_declaration(path, spec):
    path = Path(path).resolve()
    if file_hash(path) != spec["source_declaration_sha256"]:
        raise ValueError("Source declaration changed")
    document = read_json(path)
    if document["sources"] != spec["sources"]:
        raise ValueError("Source declaration metadata differs")
    for name, item in document["sources"].items():
        source = contained(path.parent, path.parent / name)
        if (
            file_hash(source) != item["sha256"]
            or source.stat().st_size != item["bytes"]
        ):
            raise ValueError("Published provenance snapshot changed")
    return document


def creator_catalog(text):
    """Retain creator assertions separately from verified source identity."""
    result, namespace = {}, None
    for line in text.splitlines():
        if line.startswith("###"):
            namespace = (
                "professional"
                if "Descriptions of each video (train professional" in line
                else "test"
                if "Descriptions of each video (test professional" in line
                else None
            )
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if namespace and len(cells) == 5 and cells[0].isdigit():
            key = namespace + "/match" + str(int(cells[0]))
            if key in result:
                raise ValueError("Duplicate creator source group assertion")
            result[key] = {
                "published_players": cells[1],
                "published_event": cells[2],
                "published_court_colors": cells[3],
                "published_frame_claim": cells[4],
                "source_identity_reviewed": False,
            }
    return result


def classify_member(name):
    parts = PurePosixPath(name).parts
    for index, part in enumerate(parts[:-3]):
        namespace = NAMESPACES.get(part.casefold())
        if namespace is None or len(parts) != index + 4:
            continue
        match, folder, leaf = parts[index + 1 :]
        if re.fullmatch(r"match[0-9]+", match) is None:
            continue
        if folder in {"ball_trajectory", "csv"} and leaf.endswith("_ball.csv"):
            rally, kind = leaf.removesuffix("_ball.csv"), "labels"
        elif folder in {"rally_video", "video"} and leaf.endswith(".mp4"):
            rally, kind = leaf.removesuffix(".mp4"), "video"
        else:
            continue
        if re.fullmatch(r"[0-9]+_[0-9]+_[0-9]+", rally) is None:
            continue
        return {
            "kind": kind,
            "namespace": namespace,
            "published_namespace": part,
            "match": match,
            "rally": rally,
            "group": f"{namespace}/{match}",
            "clip": f"{namespace}/{match}/{rally}",
        }
    if PurePosixPath(name).suffix.lower() in {".txt", ".md", ".docx", ".pdf"}:
        return {"kind": "description"}
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in {".csv", ".mp4"}:
        # An unknown layout must not make its published rows/media disappear.
        return {
            "kind": "labels" if suffix == ".csv" else "video",
            "namespace": "unrecognized",
            "published_namespace": None,
            "match": None,
            "rally": None,
            "group": "unrecognized",
            "clip": "unrecognized/" + digest(name.encode()),
        }
    return {"kind": "unrecognized"}


def census_archive(archive, limits):
    """Validate every path, including unselected members, before extraction."""
    infos = archive.infolist()
    if len(infos) > limits["members"]:
        raise ValueError("Too many archive members")
    result, seen, files = [], set(), set()
    total = selected = 0
    for info in infos:
        name = info.orig_filename
        parts = PurePosixPath(name).parts
        if (
            not parts
            or name.startswith("/")
            or "\\" in name
            or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
            or any(
                part in {".", ".."}
                or ":" in part
                or part.endswith((".", " "))
                or any(ord(char) < 32 for char in part)
                for part in parts
            )
            or any(
                re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", p)
                for p in parts
            )
        ):
            raise ValueError("Unsafe archive path")
        canonical = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
        if canonical in seen:
            raise ValueError("Duplicate or case-colliding archive path")
        seen.add(canonical)
        mode = stat.S_IFMT(info.external_attr >> 16)
        if info.flag_bits & 1 or mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise ValueError("Encrypted or special archive member")
        if (mode == stat.S_IFDIR) != info.is_dir() and mode != 0:
            raise ValueError("Conflicting archive member type")
        if not info.is_dir():
            files.add(canonical)
        total += info.file_size
        if total > limits["archive_uncompressed_bytes"]:
            raise ValueError("Archive uncompressed bytes exceed bound")
        item = {
            "path": name,
            "bytes": info.file_size,
            "compressed_bytes": info.compress_size,
            "crc32": info.CRC,
            "directory": info.is_dir(),
            **classify_member(name),
        }
        bound = {
            "labels": "csv_bytes",
            "video": "video_bytes",
            "description": "description_bytes",
        }.get(item["kind"])
        if bound and not info.is_dir():
            if info.file_size > limits[bound]:
                raise ValueError("Selected archive member exceeds bound")
            selected += info.file_size
        result.append(item)
    if selected > limits["extracted_bytes"]:
        raise ValueError("Selected extraction exceeds bound")
    for name in seen:
        if any(parent.as_posix() in files for parent in PurePosixPath(name).parents):
            raise ValueError("Archive file is also a parent directory")
    return result


def decode_clock(path, max_frames):
    """No app registration or FPS-derived replacement timestamps."""
    threaded = importlib.util.find_spec("torchvision") is not None
    if threaded:
        import torchvision  # noqa: F401  # Initialize before threaded PyAV.

    from .av_runtime import open_media
    from .orientation import display_dimensions, frame_rotation

    frames, issues = [], []
    before = (Path(path).stat().st_size, Path(path).stat().st_mtime_ns)
    with open_media(str(path)) as container:
        if len(container.streams.video) != 1:
            raise ValueError("Expected exactly one source video stream")
        stream = container.streams.video[0]
        stream.thread_type = "AUTO" if threaded else "NONE"
        if not threaded:
            stream.codec_context.thread_count = 1
        rotation = None
        width, height = stream.width, stream.height
        time_base = str(stream.time_base)
        for index, frame in enumerate(container.decode(stream)):
            if index >= max_frames:
                raise ValueError("Decoded frame count exceeds bound")
            current_rotation = frame_rotation(frame)
            if rotation is None:
                rotation = current_rotation
            if current_rotation != rotation or (frame.width, frame.height) != (
                width,
                height,
            ):
                issues.append("changing_source_geometry")
            frames.append(
                {
                    "frame": index,
                    "pts": frame.pts,
                    "time_base": str(frame.time_base),
                    "time_s": float(frame.pts * frame.time_base)
                    if frame.pts is not None and frame.time_base is not None
                    else None,
                }
            )
        if not frames:
            raise ValueError("No decoded source frames")
        times = [row["time_s"] for row in frames]
        if any(value is None or not math.isfinite(value) for value in times):
            issues.append("missing_or_nonfinite_pts")
        elif any(b <= a for a, b in itertools.pairwise(times)):
            issues.append("nonincreasing_pts")
        display = display_dimensions(width, height, rotation)
    if before != (Path(path).stat().st_size, Path(path).stat().st_mtime_ns):
        raise ValueError("Video changed while scanning native clock")
    return {
        "frames": frames,
        "frame_count": len(frames),
        "source_size": [width, height],
        "display_size": list(display),
        "rotation": rotation,
        "time_base": time_base,
        "issues": sorted(set(issues)),
    }


def normalize_csv(raw, spec, clock):
    """Retain each raw published record; ambiguous clocks/labels stay ineligible."""
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, [])
        rows = []
        for row in reader:
            if len(rows) >= spec["limits"]["rows_per_csv"]:
                raise ValueError("Published CSV row count exceeds bound")
            rows.append(row)
    except (UnicodeError, csv.Error) as exc:
        return {
            "header": None,
            "records": [],
            "record_count": None,
            "parse_error": type(exc).__name__,
            "raw_bytes": len(raw),
            "physical_lines": len(raw.splitlines()),
            "issues": ["unparsed_csv"],
        }
    supported = header == spec["csv_columns"]

    def ordinal(row):
        return int(row[0]) if row and re.fullmatch(r"[0-9]+", row[0]) else None

    counts = Counter(ordinal(row) for row in rows)
    count = clock.get("frame_count") if clock else None
    coverage = (
        count is not None
        and len(rows) == count
        and set(counts) == set(range(count))
        and all(n == 1 for n in counts.values())
    )
    geometry = (
        clock is not None
        and clock.get("source_size") == spec["nominal_geometry"]
        and clock.get("rotation") == 0
        and not clock.get("issues")
    )
    records = []
    for index, row in enumerate(rows):
        number, issues = ordinal(row), []
        if not supported or len(row) != len(header):
            issues.append("unsupported_csv_schema")
        if number is None or counts[number] != 1:
            issues.append("invalid_or_duplicate_ordinal")
        if not coverage:
            issues.append("incomplete_native_ordinal_coverage")
        if not geometry:
            issues.append("unavailable_annotation_coordinate_basis")
        flag = row[1] if supported and len(row) == 4 else None
        state = {"0": "published_not_visible", "1": "published_visible"}.get(
            flag, "unknown"
        )
        if state == "unknown":
            issues.append("unknown_published_visibility")
        point = None
        if supported and len(row) == 4:
            try:
                x, y = float(row[2]), float(row[3])
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError("Nonfinite coordinate")
                if flag == "0" and (x != 0 or y != 0):
                    issues.append("invisible_with_nonzero_coordinate")
                if flag == "1":
                    width, height = spec["nominal_geometry"]
                    if not 0 <= x < width or not 0 <= y < height:
                        issues.append("coordinate_outside_source")
                    else:
                        point = [x, y]
            except ValueError:
                issues.append("missing_or_invalid_coordinate")
        records.append(
            {
                "source_row": index,
                "raw_fields": row,
                "published_frame": number,
                "published_state": state,
                "published_point": point,
                "native_frame": clock["frames"][number]
                if coverage and number is not None
                else None,
                "coordinate_reference_eligible": not issues
                and state == "published_visible",
                "training_eligible": False,
                "issues": sorted(set(issues)),
            }
        )
    return {
        "header": header,
        "records": records,
        "record_count": len(records),
        "parse_error": None,
        "ordinal_coverage_complete": coverage,
        "missing_native_labels": sorted(set(range(count)) - set(counts))
        if count is not None
        else None,
        "issues": [] if supported else ["unsupported_csv_schema"],
    }


def _consumers():
    package = Path(__file__).resolve().parent
    files = {"badminton/" + path.name: path for path in package.glob("*.py")}
    files["scripts/prepare_shuttle_supervision.py"] = (
        package.parents[1] / "scripts/prepare_shuttle_supervision.py"
    )
    return files


def _context(root, output, declaration, manifest, spec):
    path = contained(output, output / "context.json")
    if output.exists() and (
        not output.is_dir() or (not path.exists() and any(output.iterdir()))
    ):
        raise ValueError("Choose a new or previously owned output lineage")
    for name in ("consumer", "content", "attempts"):
        contained(output, output / name)
    verify_declaration(declaration, spec)
    if read_json(manifest) != spec:
        raise ValueError("Source manifest changed during snapshot")
    files = _consumers()

    def version(name):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    context = {
        "schema_version": 1,
        "root": str(root),
        "shared_data": "data/processed",
        "manifest_sha256": file_hash(manifest),
        "source_manifest": spec,
        "declaration_sha256": file_hash(declaration),
        "archive": spec["archive"],
        "consumers": {
            name: {
                "path": contained(root, path).relative_to(root).as_posix(),
                "sha256": file_hash(path),
            }
            for name, path in sorted(files.items())
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{
                name: version(name)
                for name in ("av", "numpy", "Pillow", "psutil", "torch", "torchvision")
            },
        },
    }
    if path.exists():
        if read_json(path) != context:
            raise ValueError(
                "Frozen source/runtime context changed; use a new output lineage"
            )
    else:
        publish_json(path, context)
    for name, source in files.items():
        destination = contained(output, output / "consumer" / name)
        if destination.exists():
            if file_hash(destination) != context["consumers"][name]["sha256"]:
                raise ValueError("Frozen consumer snapshot changed")
        else:
            raw = source.read_bytes()
            if digest(raw) != context["consumers"][name]["sha256"]:
                raise ValueError("Consumer changed during snapshot")
            publish_stream(destination, io.BytesIO(raw), limit=len(raw))
    if (
        file_hash(manifest) != context["manifest_sha256"]
        or file_hash(declaration) != context["declaration_sha256"]
        or any(
            file_hash(source) != context["consumers"][name]["sha256"]
            for name, source in files.items()
        )
    ):
        raise ValueError("Source or consumer changed during snapshot")
    verify_declaration(declaration, spec)
    return context, file_hash(path)


def _seal(root, path):
    path = contained(root, path)
    return {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path)}


def _verified(root, entry):
    path = contained(root, root / entry["path"])
    if file_hash(path) != entry["sha256"]:
        raise ValueError("Completed output changed: " + entry["path"])
    return path


def _prior_proofs(root, output):
    proofs = []
    with sqlite3.connect(
        (root / "data/processed/catalog.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as cx:
        attempts = contained(output, output / "attempts")
        for path in sorted(attempts.glob("*/admission.json")):
            path = contained(output, path)
            admission = read_json(path)
            process = admission["process"]
            try:
                owner = psutil.Process(process["pid"])
                alive = abs(owner.create_time() - process["creation_time"]) < 0.01
            except psutil.NoSuchProcess:
                alive = False
            except psutil.AccessDenied as exc:
                raise ValueError("Prior process lifetime unavailable") from exc
            if alive:
                raise ValueError("Prior source preparation process is still alive")
            row = cx.execute(
                "SELECT document FROM jobs WHERE id=?", (admission["job_id"],)
            ).fetchone()
            if row is None:
                raise ValueError("Prior shared Store registration is missing")
            job = json.loads(row[0])
            if (
                job["owner_pid"] != process["pid"]
                or job["owner_started"] != process["creation_time"]
                or job["status"] not in {"completed", "failed", "interrupted"}
            ):
                raise ValueError("Prior shared Store lifetime/status is not terminal")
            proofs.append(
                {
                    "admission": _seal(output, path),
                    "original_lifetime_exited": True,
                    "store_status": job["status"],
                    "store_document_sha256": digest(row[0].encode()),
                }
            )
    return proofs


def _resume(output, receipt_path, receipt_sha, context_sha):
    if (receipt_path is None) != (receipt_sha is None):
        raise ValueError(
            "Resume requires both a terminal receipt and its recorded SHA256"
        )
    if receipt_path is None:
        return {}
    path = contained(contained(output, output / "attempts"), receipt_path)
    if file_hash(path) != receipt_sha:
        raise ValueError("Recorded terminal receipt hash changed")
    receipt = read_json(path)
    if receipt["context_sha256"] != context_sha:
        raise ValueError("Resume belongs to another source/runtime context")
    result = {}
    for entry in receipt["completed_clips"]:
        clip = read_json(_verified(output, entry))
        if clip["context_sha256"] != context_sha or clip["clip"] in result:
            raise ValueError("Conflicting completed clip checkpoint")
        result[clip["clip"]] = (clip, entry)
    return result


def _extract(archive, info, output, spec):
    """Existing final bytes must match the pinned archive, not only cached metadata."""
    key = digest(info["path"].encode())
    path = contained(
        output, output / "content" / (key + PurePosixPath(info["path"]).suffix.lower())
    )
    if path.exists():
        with archive.open(info["path"]) as source:
            checksum = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024**2), b""):
                checksum.update(chunk)
        if (
            path.stat().st_size != info["bytes"]
            or file_hash(path) != checksum.hexdigest()
        ):
            raise ValueError("Existing extracted source differs from pinned archive")
    else:
        key = {
            "labels": "csv_bytes",
            "video": "video_bytes",
            "description": "description_bytes",
        }[info["kind"]]
        with archive.open(info["path"]) as source:
            publish_stream(
                path, source, limit=spec["limits"][key], expected_bytes=info["bytes"]
            )
    return path


def _group_counts(corpus, catalog):
    groups = defaultdict(list)
    for clip in corpus:
        groups[clip["group"]].append(clip)
    result = {}
    for group, clips in sorted(groups.items()):
        labels = [label for clip in clips for label in clip["labels"]]
        rows = [row for label in labels for row in label["records"]]
        result[group] = {
            "clips": len(clips),
            "published_rows_parsed": len(rows),
            "native_frames": sum(
                clip["clock"]["frame_count"] for clip in clips if clip["clock"]
            ),
            "unparsed_csv_files": sum(
                label["record_count"] is None for label in labels
            ),
            "published_states": dict(Counter(row["published_state"] for row in rows)),
            "coordinate_reference_eligible": sum(
                row["coordinate_reference_eligible"] for row in rows
            ),
            "clock_unavailable_clips": sum(clip["clock"] is None for clip in clips),
            "creator_identity_assertion_available": group in catalog,
            "source_identity_reviewed": False,
        }
    return result


def import_archive(
    archive_path,
    output,
    attempt,
    spec,
    context_sha,
    progress,
    completed,
    reusable=None,
    catalog=None,
):
    reusable = reusable or {}
    catalog = catalog or {}
    archive_path = Path(archive_path)
    expected = spec["archive"]
    if (
        archive_path.stat().st_size != expected["bytes"]
        or file_hash(archive_path) != expected["sha256"]
    ):
        raise ValueError("Archive source size/SHA256 differs from frozen declaration")
    before = archive_path.stat().st_mtime_ns
    clips, descriptions = defaultdict(lambda: defaultdict(list)), []
    with zipfile.ZipFile(archive_path) as archive:
        census = census_archive(archive, spec["limits"])
        publish_json(attempt / "census.json", census)
        for index, item in enumerate(census):
            if item["directory"] or item["kind"] == "unrecognized":
                continue
            path = _extract(archive, item, output, spec)
            source = {**item, "extracted": _seal(output, path)}
            if item["kind"] == "description":
                descriptions.append(source)
            else:
                clips[item["clip"]][item["kind"]].append(source)
            progress(0.3 * (index + 1) / max(1, len(census)))
    references, corpus = [], []
    for index, (identity, sources) in enumerate(sorted(clips.items())):
        inputs = {key: sources.get(key, []) for key in ("labels", "video")}
        if identity in reusable:
            clip, entry = reusable[identity]
            if clip["inputs"] != inputs:
                raise ValueError("Completed clip source membership changed")
        else:
            clip = {
                "clip": identity,
                "group": identity.rsplit("/", 1)[0],
                "published_partition": identity.split("/", 1)[0],
                "context_sha256": context_sha,
                "inputs": inputs,
                "clock": None,
                "issues": [],
                "labels": [],
                "training_eligible": False,
                "independent_test_eligible": False,
                "source_identity": "publisher match namespace; cross-corpus identity unverified",
                "creator_match_assertion": catalog.get(identity.rsplit("/", 1)[0]),
                "upstream_exposure": (
                    "Published training/validation namespace; exact checkpoint membership unverified"
                    if identity.startswith(("professional/", "amateur/"))
                    else "Published upstream evaluation namespace; not a fresh holdout"
                    if identity.startswith("test/")
                    else "Unknown upstream exposure"
                ),
            }
            if len(inputs["video"]) == 1:
                media = _verified(output, inputs["video"][0]["extracted"])
                try:
                    clip["clock"] = decode_clock(
                        media, spec["limits"]["decoded_frames_per_video"]
                    )
                except (ValueError, OSError, RuntimeError) as exc:
                    clip["issues"].append(
                        "native_clock_unavailable:" + type(exc).__name__
                    )
            else:
                clip["issues"].append("missing_or_ambiguous_video")
            if len(inputs["labels"]) != 1:
                clip["issues"].append("missing_or_ambiguous_label_file")
            for labels in inputs["labels"]:
                raw = _verified(output, labels["extracted"]).read_bytes()
                normalized = normalize_csv(
                    raw, spec, clip["clock"] if len(inputs["labels"]) == 1 else None
                )
                clip["labels"].append({"source": labels["path"], **normalized})
            path = attempt / "clips" / (digest(identity.encode()) + ".json")
            publish_json(path, clip)
            entry = _seal(output, path)
        completed.append(entry)
        references.append({"clip": identity, **entry})
        corpus.append(clip)
        progress(0.3 + 0.65 * (index + 1) / max(1, len(clips)))
    if (
        before != archive_path.stat().st_mtime_ns
        or file_hash(archive_path) != expected["sha256"]
    ):
        raise ValueError("Archive changed during preparation")
    rows = [
        row for clip in corpus for label in clip["labels"] for row in label["records"]
    ]
    media_groups = defaultdict(list)
    for clip in corpus:
        for video in clip["inputs"]["video"]:
            media_groups[video["extracted"]["sha256"]].append(clip["clip"])
    aggregate = {
        "schema_version": 1,
        "context_sha256": context_sha,
        "archive_sha256": expected["sha256"],
        "members": len(census),
        "member_kinds": dict(
            Counter(item["kind"] for item in census if not item["directory"])
        ),
        "clip_count": len(corpus),
        "clips": references,
        "descriptions": descriptions,
        "published_groups": sorted({clip["group"] for clip in corpus}),
        "creator_declared_groups": len(catalog),
        "missing_creator_declared_groups": sorted(
            set(catalog) - {clip["group"] for clip in corpus}
        ),
        "group_counts": _group_counts(corpus, catalog),
        "csv_schemas": dict(
            Counter(
                json.dumps(label["header"])
                for clip in corpus
                for label in clip["labels"]
            )
        ),
        "native_geometries": dict(
            Counter(
                str(clip["clock"]["source_size"]) for clip in corpus if clip["clock"]
            )
        ),
        "partition_clip_counts": dict(
            Counter(clip["published_partition"] for clip in corpus)
        ),
        "published_rows_parsed": len(rows),
        "unparsed_csv_files": sum(
            label["record_count"] is None for clip in corpus for label in clip["labels"]
        ),
        "published_states": dict(Counter(row["published_state"] for row in rows)),
        "row_issues": dict(Counter(issue for row in rows for issue in row["issues"])),
        "coordinate_reference_eligible": sum(
            row["coordinate_reference_eligible"] for row in rows
        ),
        "native_clock_clips": sum(clip["clock"] is not None for clip in corpus),
        "native_frames": sum(
            clip["clock"]["frame_count"] for clip in corpus if clip["clock"]
        ),
        "clip_issues": dict(
            Counter(issue for clip in corpus for issue in clip["issues"])
        ),
        "incomplete_ordinal_csv_files": sum(
            label.get("ordinal_coverage_complete") is False
            for clip in corpus
            for label in clip["labels"]
        ),
        "duplicate_media_groups": [
            {"sha256": key, "clips": value}
            for key, value in sorted(media_groups.items())
            if len(value) > 1
        ],
        "training_ready_rows": 0,
        "eligibility": spec["eligibility"],
        "limitations": [
            "Published labels from a separately identified mirror, not source-reviewed application truth",
            "Native ordinal/clock checks do not certify exact original-match identity, independent splits, labels or rights",
            "Published/pretrained-source partitions are not a fresh unseen full-match evaluation",
            "No model inference, training, promotion, default change or annotation-accuracy claim",
        ],
    }
    publish_json(attempt / "report.json", aggregate)
    return {
        "report": _seal(output, attempt / "report.json"),
        "clip_count": len(corpus),
        "published_rows_parsed": len(rows),
        "training_ready_rows": 0,
    }


def run_preparation(
    root,
    output,
    declaration,
    *,
    mode,
    manifest=MANIFEST,
    archive_path=None,
    resume_receipt=None,
    resume_sha256=None,
):
    from . import config
    from .jobs import run_local_job
    from .storage import Store

    root = Path(root).resolve()
    output = contained(root / ".cache", output)
    if output == (root / ".cache").resolve():
        raise ValueError("Choose a dedicated output lineage below .cache")
    if mode not in {"fetch", "import"}:
        raise ValueError("Unknown preparation mode")
    shared = root / "data/processed"
    if (
        config.ROOT != root
        or config.DATA.resolve() != shared
        or config.WEIGHTS.resolve() != root / "models/weights"
        or not (shared / "catalog.sqlite3").is_file()
    ):
        raise ValueError(
            "Pin original roots and the existing real shared Store before imports"
        )
    spec = load_manifest(manifest)
    context, context_sha = _context(root, output, declaration, Path(manifest), spec)
    proofs = _prior_proofs(root, output)
    reusable = _resume(output, resume_receipt, resume_sha256, context_sha)
    attempt = contained(output, output / "attempts" / uuid4().hex)
    completed = []
    process = psutil.Process()
    store = Store(shared)
    job_id = None
    last_progress = -1.0

    def task(identifier, report_progress):
        nonlocal job_id, last_progress
        job_id = identifier
        publish_json(
            attempt / "admission.json",
            {
                "job_id": identifier,
                "mode": mode,
                "context_sha256": context_sha,
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": sys.argv,
                },
                "prior_terminal_proofs": proofs,
            },
        )

        def progress(value):
            nonlocal last_progress
            if value - last_progress >= 0.01:
                report_progress(value)
                last_progress = value

        def finalized(result):
            # Keep scientific completion inside shared admission: a changed
            # source/runtime must fail the Store job before it becomes completed.
            if _context(root, output, declaration, Path(manifest), spec)[0] != context:
                raise ValueError("Consumer context changed during preparation")
            return result

        if mode == "fetch":
            archive = contained(output, output / "archive.zip")
            if archive.exists():
                if (
                    archive.stat().st_size != spec["archive"]["bytes"]
                    or file_hash(archive) != spec["archive"]["sha256"]
                ):
                    raise ValueError("Existing source archive changed")
            else:
                request = urllib.request.Request(
                    spec["archive"]["url"],
                    headers={"User-Agent": "badminton-source-preparation"},
                )
                with urllib.request.urlopen(request, timeout=60) as source:
                    publish_stream(
                        archive,
                        source,
                        limit=spec["archive"]["bytes"],
                        expected_bytes=spec["archive"]["bytes"],
                        expected_sha=spec["archive"]["sha256"],
                        progress=lambda size: progress(size / spec["archive"]["bytes"]),
                    )
            return finalized({"archive": _seal(output, archive)})
        archive = contained(root / ".cache", archive_path or output / "archive.zip")
        return finalized(
            import_archive(
                archive,
                output,
                attempt,
                spec,
                context_sha,
                progress,
                completed,
                reusable,
                creator_catalog(
                    (
                        Path(declaration).resolve().parent / "dataset-description.md"
                    ).read_text(encoding="utf-8")
                ),
            )
        )

    started = time.monotonic()
    try:
        result = run_local_job(
            store, "research-shuttle-supervision-" + mode, None, task
        )
    except BaseException:
        if job_id is not None:
            publish_json(
                attempt / "terminal.json",
                {
                    "status": "failed",
                    "job_id": job_id,
                    "context_sha256": context_sha,
                    "completed_clips": completed,
                    "elapsed_s": time.monotonic() - started,
                },
            )
        raise
    terminal = attempt / "terminal.json"
    publish_json(
        terminal,
        {
            "status": "completed",
            "job_id": job_id,
            "context_sha256": context_sha,
            "completed_clips": completed,
            "elapsed_s": time.monotonic() - started,
            "result": result,
        },
    )
    return {**result, "terminal": _seal(output, terminal), "job_id": job_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fetch", "import"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--declaration", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--resume-receipt", type=Path)
    parser.add_argument("--resume-sha256")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    os.environ.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
    )
    result = run_preparation(
        root,
        args.output,
        args.declaration,
        mode=args.mode,
        manifest=args.manifest,
        archive_path=args.archive,
        resume_receipt=args.resume_receipt,
        resume_sha256=args.resume_sha256,
    )
    print(json.dumps(result, indent=2))
