"""Memory-bounded storage for the separately granted pose continuation.

This module never replays the consumed scaling/recovery entry points. Importing
it opens no media, loads no model, and changes no application or research state.
"""

import hashlib
import json
import math
import os
import stat
import struct
import zlib
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from . import aicup_pose_scaling as scaling

PROTOCOL = {
    "name": "aicup-pose-continuation-v1",
    "task": 400,
    "spec_hash": "a721a4359e08e17b809a2f5954f665abf1c3c9f502b25f99cd2a36962adb0455",
    "predecessor": {
        "task": 398,
        "scientific_commit": "8bc2b0270e6350281421d7590855627cfdfc1178",
        "prospective_sha256": "5603570cf1a40bd8dfee776c9a21b3ac44ac6e0c68073810da917ebd964c6be6",
        "claim_sha256": "7831a0d3335dd9924e12e1daf9294c4fe0923d86d27088d4ae5c82689dde6357",
        "failure_sha256": "f0c31fc5564f76254320d999d4367b1c4223afd43685917bec37d814565cda19",
        "preservation_sha256": "10598be437b8d3b3ff1d262e3f15aed29e7232f98447fdbf6688053f87262c1c",
        "original_deadline": 1793905768.8576179,
        "decoded_frame_visits": 6502,
        "model_observations_exact": None,
        "model_observations_lower": 2200,
        "model_observations_upper": 3251,
        "real_fits": 0,
    },
    "limits": {
        "task_seconds": 57600,
        "operation_seconds": 43200,
        "extra_headroom_seconds": 7200,
        "decoded_frame_visits": 276943,
        "model_observations": 138997,
        "real_fits": 1,
        "scratch_bytes": 8589934592,
        "retained_bytes": 8589934592,
        "combined_bytes": 17179869184,
        "minimum_disk_free_bytes": 2147483648,
        "cache_ram_bytes": 67108864,
        "minimum_ram_free_bytes": 536870912,
        "record_bytes": 5242880,
        "index_manifest_bytes": 1048576,
        "reconstruction_frames": 2,
        "frames_per_clip": 1416,
    },
    "expected": {
        "all_clips": 447,
        "all_reference_rows": 5037,
        "validation_rows": 353,
        "pilot_clips_reused": 45,
        "completed_clips_reused": 4,
        "all_features_reused": 844,
        "remaining_clips": 398,
        "remaining_frames": 138997,
        "remaining_reference_rows": 4193,
        "failed_clip_frames": 1051,
    },
    "frame_storage": {
        "codec": "zlib level1 exact native ndarray/planes",
        "bounded_decompression": True,
        "formats": ["yuv420p", "yuv422p", "yuv444p", "rgb24", "bgr24", "bgr0", "rgb0"],
        "maximum_dimensions": [1280, 720],
        "source_clock_color_orientation_preserved": True,
        "old_outputs_modified": False,
    },
    "training_ready": False,
    "independent_accuracy_established": False,
    "model_installed_in_app": False,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def no_links(path, root):
    """Verify lexical containment and every existing component, including root."""
    path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
    require(path.is_relative_to(root), "Spool escapes its exclusive run")
    for candidate in (root, *reversed(path.parents), path):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            require(
                not stat.S_ISLNK(info.st_mode)
                and not getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024),
                "Spool path contains a link or reparse point",
            )
    require(path.resolve().is_relative_to(root.resolve()), "Spool resolves outside run")
    return path


def record_layout(record):
    """Validate size before decompression or AVFrame/ndarray construction."""
    limits = PROTOCOL["limits"]
    require(record.get("dtype") == "uint8", "Unsupported native cache dtype")
    shape = record.get("shape")
    require(
        isinstance(shape, list)
        and 1 <= len(shape) <= 3
        and all(type(n) is int and 0 < n <= limits["record_bytes"] for n in shape),
        "Invalid native cache shape",
    )
    count = math.prod(shape)
    require(
        count <= limits["record_bytes"], "Native cache expansion exceeds record bound"
    )
    require(
        record.get("format") in PROTOCOL["frame_storage"]["formats"],
        "Unsupported native cache format",
    )
    if "planes" in record:
        dimensions, planes = record.get("dimensions"), record["planes"]
        require(record["format"] in ("bgr0", "rgb0"), "Unsupported native plane format")
        require(
            isinstance(dimensions, list)
            and len(dimensions) == 2
            and all(type(n) is int and n > 0 for n in dimensions)
            and dimensions[0] <= 1280
            and dimensions[1] <= 720,
            "Invalid native plane dimensions",
        )
        require(
            isinstance(planes, list) and len(planes) == 1, "Invalid native plane count"
        )
        plane = planes[0]
        require(
            isinstance(plane, dict)
            and all(
                type(plane.get(k)) is int and plane[k] > 0
                for k in ("size", "line_size", "height")
            )
            and plane["height"] == dimensions[1]
            and dimensions[0] * 4 <= plane["line_size"] <= dimensions[0] * 4 + 4096
            and plane["size"] == plane["height"] * plane["line_size"] == count
            and len(shape) == 1,
            "Invalid native plane stride or size",
        )
    else:
        fmt = record["format"]
        require(fmt not in ("bgr0", "rgb0"), "Packed format requires plane layout")
        if fmt in ("rgb24", "bgr24"):
            require(len(shape) == 3 and shape[2] == 3, "Invalid RGB shape")
            height, width = shape[:2]
        elif fmt == "yuv444p":
            require(len(shape) == 3 and shape[0] == 3, "Invalid YUV444 shape")
            height, width = shape[1:]
        else:
            require(len(shape) == 2, "Invalid YUV shape")
            width = shape[1]
            if fmt == "yuv420p":
                require(shape[0] % 3 == 0 and width % 2 == 0, "Invalid YUV420 shape")
                height = shape[0] * 2 // 3
            elif fmt == "yuv422p":
                require(shape[0] % 2 == 0 and width % 2 == 0, "Invalid YUV422 shape")
                height = shape[0] // 2
        require(
            0 < width <= 1280 and 0 < height <= 720,
            "Native cache dimensions exceed cohort bound",
        )
    for key in ("colorspace", "color_range", "pts"):
        require(type(record.get(key)) is int, "Invalid native color or source PTS")
    base = record.get("time_base")
    require(
        isinstance(base, list)
        and len(base) == 2
        and all(type(n) is int and n > 0 for n in base),
        "Invalid native time base",
    )
    digest = record.get("raw_sha256")
    require(
        isinstance(digest, str)
        and len(digest) == 64
        and all(c in "0123456789abcdef" for c in digest),
        "Invalid native raw seal",
    )
    return count


def bounded_record(record):
    """Check complete stream and exact length without allocating its expansion."""
    count = record_layout(record)
    data = record.get("compressed_pixels")
    require(
        isinstance(data, bytes) and len(data) <= PROTOCOL["limits"]["record_bytes"],
        "Invalid compressed native record",
    )
    decoder = zlib.decompressobj()
    raw = decoder.decompress(data, count + 1)
    require(
        len(raw) == count
        and decoder.eof
        and not decoder.unconsumed_tail
        and not decoder.unused_data,
        "Incomplete, trailing or oversized native expansion",
    )
    require(
        hashlib.sha256(raw).hexdigest() == record["raw_sha256"],
        "Native cache pixels changed",
    )
    return count


class FrameSpool:
    """Exclusive per-clip spool with sealed records and a two-frame read cache.

    Readers never decode source media. Unexpected termination preserves all owned
    files; only explicit successful cleanup removes these exact transient files.
    """

    def __init__(self, directory, run_root, check):
        self.directory = no_links(directory, run_root)
        self.run_root, self.check = Path(run_root), check
        self.directory.mkdir(exist_ok=False)
        self.path = self.directory / "pixels.bin"
        self.stream = self.path.open("xb+")
        self.identity = self.path.stat()
        self.entries, self.live = [], OrderedDict()
        self.size, self.index_size = 0, 2
        self.sealed = False

    def guard(self, reserve=0):
        import psutil

        no_links(self.path, self.run_root)
        current = self.path.stat()
        require(
            (current.st_dev, current.st_ino)
            == (self.identity.st_dev, self.identity.st_ino),
            "Spool file identity changed",
        )
        require(
            psutil.virtual_memory().available
            >= PROTOCOL["limits"]["minimum_ram_free_bytes"],
            "Insufficient free RAM for disk-backed cache",
        )
        manifest = no_links(self.directory / "manifest.json", self.run_root)
        metadata_bytes = manifest.stat().st_size if manifest.exists() else 0
        require(
            self.size + metadata_bytes + reserve <= PROTOCOL["limits"]["scratch_bytes"],
            "Spool scratch cap exceeded",
        )
        require(
            psutil.disk_usage(self.directory).free
            >= reserve + PROTOCOL["limits"]["minimum_disk_free_bytes"],
            "Insufficient disk reserve for native spool",
        )
        self.check(reserve=reserve)

    def append(self, ordinal, timestamp, frame):
        require(
            not self.sealed
            and len(self.entries) < PROTOCOL["limits"]["frames_per_clip"],
            "Spool already sealed or frame cap exceeded",
        )
        require(
            type(ordinal) is int and ordinal == len(self.entries),
            "Spool native ordinals changed",
        )
        require(
            type(timestamp) in (int, float) and math.isfinite(timestamp),
            "Invalid spool timestamp",
        )
        require(
            0 < frame.width <= 1280 and 0 < frame.height <= 720,
            "Frame dimensions exceed cohort",
        )
        native_bytes = sum(p.buffer_size for p in frame.planes)
        # Conservatively include compression/roundtrip temporaries, the source
        # frame and two reader frames rather than treating the LRU as all RAM.
        require(
            14 * native_bytes
            + PROTOCOL["limits"]["record_bytes"]
            + PROTOCOL["limits"]["index_manifest_bytes"]
            <= PROTOCOL["limits"]["cache_ram_bytes"],
            "Frame temporaries exceed cache RAM bound",
        )
        self.guard(PROTOCOL["limits"]["record_bytes"])
        record = scaling.pack_frame(frame)
        bounded_record(record)
        pixels = record.pop("compressed_pixels")
        header = encoded({"ordinal": ordinal, "timestamp": timestamp, "record": record})
        require(len(header) <= 16384, "Spool record header exceeds bound")
        size = 4 + len(header) + len(pixels)
        require(
            size <= PROTOCOL["limits"]["record_bytes"],
            "Serialized native record exceeds cap",
        )
        entry = {
            "offset": self.size,
            "size": size,
            "header_bytes": len(header),
            "sha256": hashlib.sha256(
                struct.pack("<I", len(header)) + header + pixels
            ).hexdigest(),
        }
        self.index_size += len(encoded(entry)) + 1
        require(
            self.index_size + 4096 <= PROTOCOL["limits"]["index_manifest_bytes"],
            "Spool index exceeds metadata bound",
        )
        self.stream.seek(self.size)
        self.stream.write(struct.pack("<I", len(header)))
        self.stream.write(header)
        self.stream.write(pixels)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.size += size
        self.entries.append(entry)
        self.guard()

    def seal(self):
        require(not self.sealed and self.entries, "Cannot seal empty or sealed spool")
        self.guard()
        manifest = {
            "frames": len(self.entries),
            "bytes": self.size,
            "entries": self.entries,
        }
        payload = encoded(manifest)
        require(
            len(payload) <= PROTOCOL["limits"]["index_manifest_bytes"],
            "Spool manifest exceeds cap",
        )
        self.guard(reserve=len(payload))
        with (self.directory / "manifest.json").open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        self.manifest_sha256 = hashlib.sha256(payload).hexdigest()
        self.sealed = True

    def verify_manifest(self):
        path = no_links(self.directory / "manifest.json", self.run_root)
        require(
            path.stat().st_size <= PROTOCOL["limits"]["index_manifest_bytes"],
            "Spool manifest exceeds bound",
        )
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == self.manifest_sha256,
            "Spool manifest changed",
        )

    def frame(self, ordinal):
        require(
            self.sealed and type(ordinal) is int and 0 <= ordinal < len(self.entries),
            "Unsealed spool or invalid reader ordinal",
        )
        self.guard()
        require(self.path.stat().st_size == self.size, "Spool truncated or extended")
        self.verify_manifest()
        entry = self.entries[ordinal]
        self.stream.seek(entry["offset"])
        blob = self.stream.read(entry["size"])
        require(
            len(blob) == entry["size"]
            and hashlib.sha256(blob).hexdigest() == entry["sha256"],
            "Spool record changed",
        )
        require(
            struct.unpack("<I", blob[:4])[0] == entry["header_bytes"],
            "Spool header changed",
        )
        end = 4 + entry["header_bytes"]
        header = json.loads(blob[4:end])
        require(header["ordinal"] == ordinal, "Spool ordinal seal changed")
        record = header["record"] | {"compressed_pixels": blob[end:]}
        bounded_record(record)
        if ordinal not in self.live:
            if len(self.live) >= PROTOCOL["limits"]["reconstruction_frames"]:
                self.live.popitem(last=False)
            # The original reconstruction only sees fully validated, bounded
            # streams; native format and exact RGB/BGR conversion stay unchanged.
            self.live[ordinal] = scaling.unpack_frame(record)
        self.live.move_to_end(ordinal)
        self.guard()
        return header["ordinal"], header["timestamp"], self.live[ordinal]

    def close(self):
        self.live.clear()
        self.stream.close()

    def cleanup(self):
        require(
            self.stream.closed and self.sealed,
            "Cleanup requires closed successful spool",
        )
        no_links(self.directory, self.run_root)
        require(
            {p.name for p in self.directory.iterdir()}
            == {"pixels.bin", "manifest.json"},
            "Unexpected spool file; preserve evidence",
        )
        current = self.path.stat()
        require(
            (current.st_dev, current.st_ino)
            == (self.identity.st_dev, self.identity.st_ino),
            "Spool identity changed before cleanup",
        )
        require(current.st_size == self.size, "Changed spool size before cleanup")
        self.verify_manifest()
        with self.path.open("rb") as stream:
            for entry in self.entries:
                blob = stream.read(entry["size"])
                require(
                    hashlib.sha256(blob).hexdigest() == entry["sha256"],
                    "Changed spool record before cleanup",
                )
        for path in (self.path, self.directory / "manifest.json"):
            no_links(path, self.run_root)
            path.unlink()
        self.directory.rmdir()


@contextmanager
def decode_spool(video, root, times, progress, directory, run_root, check):
    """Decode once and serve exact native frames to court/tracker consumers."""
    from . import court_detection, tracking
    from .video import iter_frames, resolve_source

    spool = FrameSpool(directory, run_root, check)
    old_tracking, old_court = tracking.iter_frames, court_detection.iter_frames
    success = False

    def frames(requested, requested_root, requested_times, start, end):
        require(
            requested == video
            and Path(requested_root).resolve() == Path(root).resolve()
            and list(requested_times) == list(times)
            and type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(spool.entries),
            "Spool reader changed source, clock or range",
        )
        for index in range(start, end):
            yield spool.frame(index)

    try:
        for ordinal, timestamp, frame in iter_frames(
            video, root, times, 0, video["frame_count"]
        ):
            require(
                ordinal < len(times) and timestamp == times[ordinal],
                "Spool source clock changed",
            )
            spool.append(ordinal, timestamp, frame)
            progress(len(spool.entries))
        require(
            len(spool.entries) == video["frame_count"],
            "Incomplete spool source coverage",
        )
        spool.seal()
        tracking.iter_frames = court_detection.iter_frames = frames
        yield len(spool.entries)
        resolve_source(video, root)
        success = True
    finally:
        tracking.iter_frames, court_detection.iter_frames = old_tracking, old_court
        spool.close()
        if success:
            spool.cleanup()
