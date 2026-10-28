"""Exhaustive scene-review preparation; no source judgments or model execution."""

from __future__ import annotations

import hashlib
import io
import os
import stat
from collections import Counter
from fractions import Fraction
from pathlib import Path, PurePosixPath

from .shuttle_context_audit import ELIGIBILITY, encode
from .shuttle_context_audit import decode as _decode

TILE = (320, 180)
CAPTION = 36
SHEET = (1280, 864)
MAX_BYTES = 6 * 1024**2
MAX_IMAGES = 20
MAX_OUTPUT_BYTES = 2 * 1024**3
LANES = ("independent_a", "independent_b")
KINDS = ("live", "replay", "non_play", "unknown")


def decode(raw):
    value = _decode(raw)
    encode(value)  # Reject numeric overflow to infinity as well as JSON constants.
    return value


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        before = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024**2), b""):
            result.update(block)
        after = os.fstat(stream.fileno())
        # Windows Python 3.12 can expose change time through fstat but creation
        # time through Path.stat. Compare handles to handles, preserving all
        # identity/version fields instead of dropping the change-time guard.
        with Path(path).open("rb") as named:
            current = os.fstat(named.fileno())
    keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(
        all(
            getattr(before, k) == getattr(after, k) == getattr(current, k) for k in keys
        ),
        "Input changed while hashing",
    )
    return result.hexdigest()


def safe_path(root, name, *, must_exist=True):
    require(
        type(name) is str and bool(name) and "\\" not in name, "Relative path required"
    )
    relative = PurePosixPath(name)
    require(
        not relative.is_absolute()
        and str(relative) == name
        and all(p not in (".", "..") and ":" not in p for p in relative.parts),
        "Unsafe artifact path",
    )
    root = Path(root)
    path = root
    for part in (None, *relative.parts):
        if part is not None:
            path /= part
        try:
            info = path.lstat()
        except FileNotFoundError:
            require(not must_exist, "Missing bound artifact")
            continue
        require(
            not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & 1024,
            "Linked artifact is unsupported",
        )
    require(path.resolve().is_relative_to(root.resolve()), "Artifact escapes root")
    if must_exist:
        require(path.is_file(), "Ordinary artifact file required")
    return path


def integer(value, minimum=0):
    require(type(value) is int and value >= minimum, "Strict integer required")
    return value


def clock_time(pts, time_base):
    require(
        type(pts) is int and type(time_base) is str, "Native PTS/time base required"
    )
    try:
        base = Fraction(time_base)
    except (ValueError, ZeroDivisionError):
        raise ValueError("Invalid native time base") from None
    require(base > 0, "Positive native time base required")
    return pts * base


def inventory(raw, diagnostics, protocol):
    """Consume only the already projected metadata, never original scientific rows."""
    require(
        raw.get("schema_version") == 1
        and raw.get("origin_diagnostics_sha256") == digest(encode(diagnostics)),
        "Inventory diagnostic provenance changed",
    )
    require(diagnostics.get("eligibility") == ELIGIBILITY, "Eligibility changed")
    views, cases = raw.get("views"), raw.get("cases")
    require(
        isinstance(views, list) and isinstance(cases, list), "Missing full inventory"
    )
    require(
        len(views) == protocol["denominators"]["views"]
        and len(cases) == protocol["denominators"]["cases"],
        "Full case/view denominator changed",
    )
    require(
        set(diagnostics.get("methods", {})) == {"control", "decoder", "convolution"},
        "Original method denominator changed",
    )
    for original in diagnostics["methods"].values():
        require(
            len(original["views"]) == len(views)
            and [c["case"] for c in original["cases"]] == cases,
            "Original case/view inventory differs from projection",
        )
    sources = {v["id"]: v for v in protocol["sources"]}
    require(len(sources) == len(protocol["sources"]), "Duplicate source identity")
    seen_views, seen_cases, membership = set(), set(), Counter()
    clean = []
    for index, view in enumerate(views):
        require(
            set(view) == {"id", "video_id", "start_frame", "end_frame", "case_ids"},
            "Exact projected view shape required",
        )
        identifier, source = view["id"], view["video_id"]
        require(
            type(identifier) is str
            and bool(identifier)
            and identifier not in seen_views,
            "Duplicate/missing view",
        )
        require(type(source) is str and source in sources, "Unknown source")
        start, end = integer(view["start_frame"]), integer(view["end_frame"], 1)
        require(start < end <= sources[source]["frame_count"], "Invalid source window")
        members = view["case_ids"]
        require(
            isinstance(members, list) and all(type(v) is str for v in members),
            "Invalid case membership",
        )
        require(len(members) == len(set(members)), "Duplicate view member")
        seen_views.add(identifier)
        membership.update(members)
        original = diagnostics["methods"]["control"]["views"][index]
        for method in ("control", "decoder", "convolution"):
            require(
                diagnostics["methods"][method]["views"][index]["view"] == view,
                "Methods disagree on source view inventory",
            )
        segments = original["segments"]
        cursor, boundaries = start, []
        for segment in segments:
            require(
                integer(segment["start_frame"]) == cursor,
                "Noncontiguous original context partition",
            )
            next_frame = integer(segment["end_frame"], 1)
            require(next_frame > cursor, "Reversed original context partition")
            cursor = next_frame
            require(cursor <= end, "Context partition exceeds view")
            boundaries.append(segment["start_frame"])
        require(cursor == end and boundaries, "Missing original context partitions")
        clean.append({**view, "index": index, "partition_starts": boundaries})
    for case in cases:
        require(
            set(case) == {"id", "video_id", "frame"},
            "Exact projected case shape required",
        )
        require(
            type(case["id"]) is str and case["id"] not in seen_cases, "Duplicate case"
        )
        require(membership[case["id"]] == 1, "Unavailable/ambiguous case membership")
        view = next(v for v in clean if case["id"] in v["case_ids"])
        require(
            case["video_id"] == view["video_id"]
            and view["start_frame"] <= integer(case["frame"]) < view["end_frame"],
            "Case source/frame mismatch",
        )
        seen_cases.add(case["id"])
    require(set(membership) == seen_cases, "Unaccounted original case membership")
    require(
        sum(v["end_frame"] - v["start_frame"] for v in clean)
        == protocol["denominators"]["frame_occurrences"],
        "Native frame occurrence denominator changed",
    )
    return clean, cases


def native_frames(path):
    """Sequential native decode with one decoder thread; no neural imports."""
    from .av_runtime import open_media
    from .orientation import frame_rotation, orient_frame

    previous, rotation, dimensions = None, None, None
    with open_media(str(path)) as container:
        require(bool(container.streams.video), "Source has no video stream")
        stream = container.streams.video[0]
        stream.thread_type = "NONE"
        stream.codec_context.thread_count = 1
        for index, frame in enumerate(container.decode(stream)):
            base = str(frame.time_base)
            current = clock_time(frame.pts, base)
            require(
                previous is None or current > previous,
                "Native clock reversal/duplicate",
            )
            previous = current
            actual_rotation = frame_rotation(frame)
            if rotation is None:
                rotation = actual_rotation
            require(rotation == actual_rotation, "Source orientation changed")
            display = orient_frame(frame, expected_rotation=rotation)
            actual_dimensions = [display.width, display.height]
            if dimensions is None:
                dimensions = actual_dimensions
            require(
                dimensions == actual_dimensions, "Source display dimensions changed"
            )
            yield (
                {
                    "frame": index,
                    "pts": frame.pts,
                    "time_base": base,
                    "rotation": rotation,
                    "display_size": dimensions[:],
                },
                display,
            )


def cell_image(frame):
    from PIL import Image, ImageOps

    # Contain, rather than crop: no source content is removed from the tile.
    return ImageOps.pad(
        frame.to_image().convert("RGB"),
        TILE,
        method=Image.Resampling.LANCZOS,
        color="black",
    )


class GalleryBuilder:
    def __init__(self, view, publish):
        self.view, self.publish = view, publish
        self.members, self.sheets, self.image = [], [], None
        self.expected = view["start_frame"]

    def add(self, clock, tile):
        from PIL import Image, ImageDraw

        frame = clock["frame"]
        require(
            frame == self.expected and frame < self.view["end_frame"],
            "Missing or reordered frame",
        )
        require(
            clock["display_size"][0] > 0 and clock["display_size"][1] > 0,
            "Invalid display size",
        )
        if self.image is None:
            self.image = Image.new("RGB", SHEET, "black")
        partition = max(
            i for i, start in enumerate(self.view["partition_starts"]) if start <= frame
        )
        local = len(self.members)
        x, y = (local % 4) * TILE[0], (local // 4) * (TILE[1] + CAPTION)
        self.image.paste(tile, (x, y))
        draw = ImageDraw.Draw(self.image)
        draw.text(
            (x + 3, y + TILE[1] + 1), f"f={frame} PTS={clock['pts']}", fill="white"
        )
        draw.text(
            (x + 3, y + TILE[1] + 12),
            f"tb={clock['time_base']} t={float(clock_time(clock['pts'], clock['time_base'])):.6f}",
            fill="white",
        )
        begins = frame in self.view["partition_starts"]
        draw.text(
            (x + 3, y + TILE[1] + 23),
            f"partition={partition}" + (" BEGINS" if begins else ""),
            fill="white",
        )
        self.members.append(
            {**clock, "partition": partition, "partition_begins": begins}
        )
        self.expected += 1
        if len(self.members) == 16 or self.expected == self.view["end_frame"]:
            self.flush()

    def flush(self):
        from PIL import ImageDraw

        require(bool(self.members), "Empty gallery sheet")
        draw = ImageDraw.Draw(self.image)
        for local in range(len(self.members), 16):
            draw.text(
                ((local % 4) * TILE[0] + 5, (local // 4) * (TILE[1] + CAPTION) + 5),
                "EMPTY CELL",
                fill="white",
            )
        buffer = io.BytesIO()
        self.image.save(
            buffer, format="JPEG", quality=80, subsampling=0, optimize=False
        )
        raw = buffer.getvalue()
        name = f"view-{self.view['index']:03d}/sheet-{len(self.sheets):03d}.jpg"
        self.publish(name, raw)
        self.sheets.append(
            {
                "path": name,
                "sha256": digest(raw),
                "bytes": len(raw),
                "size": list(SHEET),
                "members": self.members,
                "empty_cells": 16 - len(self.members),
            }
        )
        self.members, self.image = [], None

    def finish(self):
        require(
            self.expected == self.view["end_frame"] and self.image is None,
            "Incomplete native view",
        )
        return {"view": self.view, "sheets": self.sheets}


def prepare_sources(protocol, views, paths, publish, progress=lambda value: None):
    """Decode each entire original source once; retain every view occurrence."""
    builders = [GalleryBuilder(v, publish) for v in views]
    clocks = {}
    for source_index, source in enumerate(protocol["sources"]):
        sid = source["id"]
        current = [b for b in builders if b.view["video_id"] == sid]
        rows = []
        for clock, frame in native_frames(paths[source["artifact"]]):
            require(clock["frame"] == len(rows), "Native decoder sequence changed")
            require(len(rows) < source["frame_count"], "Extra native source frame")
            require(
                clock["rotation"] == source["rotation"]
                and clock["display_size"] == source["display_size"],
                "Frozen source orientation/dimensions changed",
            )
            rows.append(clock)
            wanted = [
                b
                for b in current
                if b.view["start_frame"] <= clock["frame"] < b.view["end_frame"]
            ]
            if wanted:
                tile = cell_image(frame)
                for builder in wanted:
                    builder.add(clock, tile)
            if len(rows) % 250 == 0:
                progress(
                    (source_index + len(rows) / source["frame_count"])
                    / len(protocol["sources"])
                )
        require(len(rows) == source["frame_count"], "Incomplete native source decode")
        clocks[sid] = rows
    galleries = [b.finish() for b in builders]
    require(
        sum(len(g["sheets"]) for g in galleries) == protocol["denominators"]["sheets"],
        "Derived sheet denominator changed",
    )
    return {"schema_version": 1, "galleries": galleries, "source_clocks": clocks}


def pack_galleries(galleries, *, max_bytes=MAX_BYTES, max_images=MAX_IMAGES):
    """Pack every sheet twice independently; count overlap bytes each time."""
    require(type(max_bytes) is int and 0 < max_bytes <= MAX_BYTES, "Invalid byte cap")
    require(
        type(max_images) is int and 0 < max_images <= MAX_IMAGES, "Invalid image cap"
    )
    original_sheets = sum(len(g["sheets"]) for g in galleries)
    frames = sum(sum(len(s["members"]) for s in g["sheets"]) for g in galleries)
    original_bytes = sum(s["bytes"] for g in galleries for s in g["sheets"])
    plans = []
    unavailable = []
    for gallery in galleries:
        sheets = gallery["sheets"]
        require(bool(sheets), "Missing full gallery view")
        for sheet in sheets:
            integer(sheet["bytes"], 1)
        cursor, previous = 0, None
        while cursor < len(sheets):
            start = cursor
            selected = [] if previous is None else [previous]
            size = sum(s["bytes"] for s in selected)
            while (
                cursor < len(sheets)
                and len(selected) < max_images
                and size + sheets[cursor]["bytes"] <= max_bytes
            ):
                selected.append(sheets[cursor])
                size += sheets[cursor]["bytes"]
                cursor += 1
            if cursor == start:
                unavailable.append(
                    {
                        "view_index": gallery["view"]["index"],
                        "sheet_index": cursor,
                        "reason": "image_or_overlap_exceeds_session_cap",
                    }
                )
                break
            plans.append(
                {
                    "view_index": gallery["view"]["index"],
                    "index": len(plans),
                    "images": [
                        {k: s[k] for k in ("path", "sha256", "bytes")} for s in selected
                    ],
                    "overlap_image": previous["path"] if previous else None,
                    "new_images": [s["path"] for s in sheets[start:cursor]],
                    "total_image_bytes": size,
                    "image_count": len(selected),
                }
            )
            previous = selected[-1]
    feasible = not unavailable
    summary = {
        "status": "planned" if feasible else "unavailable",
        "views": len(galleries),
        "sheets_per_pass": original_sheets,
        "native_frame_occurrences_per_pass": frames,
        "original_image_bytes_per_pass": original_bytes,
        "unavailable_views": len(unavailable),
        "max_session_bytes": max_bytes,
        "max_session_images": max_images,
        "sessions_per_pass": len(plans) if feasible else None,
        "image_occurrences_per_pass": sum(p["image_count"] for p in plans)
        if feasible
        else None,
        "payload_bytes_per_pass": sum(p["total_image_bytes"] for p in plans)
        if feasible
        else None,
        "new_assessor_sessions": 0,
        "new_image_transfer_bytes": 0,
        "lanes": list(LANES),
        "adjudication_reserve": {
            "max_additional_passes": 1,
            "sessions": len(plans) if feasible else None,
            "image_payload_bytes": sum(p["total_image_bytes"] for p in plans)
            if feasible
            else None,
            "purpose": "Prospective ceiling only; no execution or label acceptance authority",
        },
    }
    if feasible:
        summary.update(
            two_pass_sessions=2 * len(plans),
            two_pass_payload_bytes=2 * summary["payload_bytes_per_pass"],
            overlap_image_occurrences_per_pass=summary["image_occurrences_per_pass"]
            - original_sheets,
        )
    # Failed packing supplies no partial substitute schedule or smaller denominator.
    return summary, {
        "lanes": {lane: plans if feasible else [] for lane in LANES},
        "unavailable": unavailable,
    }


def validate_gallery_manifest(manifest, views, protocol):
    require(manifest.get("schema_version") == 1, "Invalid gallery schema")
    require(len(manifest["galleries"]) == len(views), "Missing native gallery view")
    for gallery, view in zip(manifest["galleries"], views):
        require(gallery["view"] == view, "Gallery source/context membership changed")
        expected, clocks = (
            view["start_frame"],
            manifest["source_clocks"][view["video_id"]],
        )
        for index, sheet in enumerate(gallery["sheets"]):
            require(
                sheet["path"] == f"view-{view['index']:03d}/sheet-{index:03d}.jpg",
                "Gallery path/membership changed",
            )
            require(sheet["size"] == list(SHEET), "Gallery dimensions changed")
            members = sheet["members"]
            require(
                1 <= len(members) <= 16 and sheet["empty_cells"] == 16 - len(members),
                "Invalid partial sheet",
            )
            require(
                index == len(gallery["sheets"]) - 1 or len(members) == 16,
                "Unexpected partial interior sheet",
            )
            for member in members:
                require(
                    member["frame"] == expected and expected < view["end_frame"],
                    "Native gallery coverage changed",
                )
                partition = max(
                    i
                    for i, start in enumerate(view["partition_starts"])
                    if start <= expected
                )
                require(
                    member
                    == {
                        **clocks[expected],
                        "partition": partition,
                        "partition_begins": expected in view["partition_starts"],
                    },
                    "Native clock/orientation/partition changed",
                )
                expected += 1
        require(expected == view["end_frame"], "Missing original native frame")
    require(
        set(manifest["source_clocks"]) == {s["id"] for s in protocol["sources"]},
        "Source denominator changed",
    )
    for source in protocol["sources"]:
        rows = manifest["source_clocks"][source["id"]]
        require(
            len(rows) == source["frame_count"], "Full source clock denominator changed"
        )
        previous = None
        for index, row in enumerate(rows):
            require(
                type(row["frame"]) is int and row["frame"] == index,
                "Clock frame changed",
            )
            current = clock_time(row["pts"], row["time_base"])
            require(previous is None or current > previous, "Clock reversal/duplicate")
            require(
                type(row["rotation"]) is int and row["rotation"] in (0, 90, 180, 270),
                "Unsupported orientation",
            )
            require(
                len(row["display_size"]) == 2
                and all(type(n) is int and n > 0 for n in row["display_size"]),
                "Invalid display size",
            )
            require(
                row["rotation"] == source["rotation"]
                and row["display_size"] == source["display_size"],
                "Frozen display metadata changed",
            )
            previous = current


def audit_images(manifest, output):
    from PIL import Image

    total = 0
    for gallery in manifest["galleries"]:
        for sheet in gallery["sheets"]:
            path = safe_path(output, sheet["path"])
            raw = path.read_bytes()
            require(
                len(raw) == sheet["bytes"] and digest(raw) == sheet["sha256"],
                "Derived image bytes changed",
            )
            with Image.open(io.BytesIO(raw)) as image:
                require(
                    image.format == "JPEG"
                    and image.mode == "RGB"
                    and image.size == SHEET,
                    "Derived image format changed",
                )
                image.load()
            total += len(raw)
    return total


def audit_native_clocks(manifest, protocol, paths):
    for source in protocol["sources"]:
        expected = manifest["source_clocks"][source["id"]]
        count = 0
        for clock, _ in native_frames(paths[source["artifact"]]):
            require(
                count < len(expected) and clock == expected[count],
                "Independent native clock/orientation mismatch",
            )
            count += 1
        require(count == len(expected), "Independent decode is incomplete")


def aggregate(manifest, packing):
    return {
        **packing,
        "source_counts": [
            {
                "source_id": sid,
                "decoded_source_frames": len(rows),
                "rotation": rows[0]["rotation"] if rows else None,
                "display_size": rows[0]["display_size"] if rows else None,
            }
            for sid, rows in sorted(manifest["source_clocks"].items())
        ],
        "eligibility": dict(ELIGIBILITY),
        "complete_independent_rally_references": "0/2",
        "full_match_accuracy_established": False,
        "limitations": [
            "Derived thumbnails can support future coarse scene review only; insufficient detail remains unknown.",
            "Every frame occurrence is represented, but no scene labels or review completeness are established.",
            "Context partition boundaries retain original metadata; they are not independently reviewed camera edits.",
            "A future assessment requires separately frozen payload/destination/session authority.",
        ],
    }
