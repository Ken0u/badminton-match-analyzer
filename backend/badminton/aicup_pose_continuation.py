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
import sys
import time
import zipfile
import zlib
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from . import aicup_pose_scaling as scaling

read, digest, publish = scaling.read_json, scaling.digest, scaling.publish
producer, actor, learning = scaling.producer, scaling.actor, scaling.learning

PROTOCOL = {
    "name": "aicup-pose-continuation-v1",
    "code_task": 404,
    "task": 405,
    "spec_hash": "e76e1629e4f7fc63916991ac90a389297548402df7956e398ef58bd5893ddfdb",
    "grant": {
        "actor": "Ken0u",
        "host_id": "MSI",
        "resources": ["gpu:windows-primary", "cpu:windows-training"],
        "observation_seconds": 300,
    },
    "prior_admission": {
        "task": 402,
        "source": "b0bf6421cbb0ad11e5e6fb7203f168d449f98d9f",
        "granted_at": 1794094747,
        "deadline": 1794152347,
        "failure_sha256": "53d028580f96714b38858554b144a88980dfdb9e15315374435e550aa61c3819",
        "integrity_sha256": "86a371b2e0b780b5972b75e2ccc73d624ca8d01de019d58d58bf32cb0ab0dd6a",
    },
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
        "minimum_forecast_seconds": 27834,
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
        "journal_record_bytes": 1024,
        "terminal_bytes": 65536,
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
        "display_axes_may_be_swapped": True,
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


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def live_grant(observation, source_revision, now=None):
    """Validate a recent authenticated parent observation before any science.

    The parent obtains this document from the trusted coordination branch.
    The scientific child receives its private path, never GitHub credentials.
    Lease renewals may extend expires_at, never the initial scientific window.
    """
    now = time.time() if now is None else now
    require(finite(now), "Invalid grant observation time")
    try:
        task, receipt = observation["task"], observation["grant_receipt"]
        claim, code = task["claim"], observation["code_task"]
        immutable = (
            "actor",
            "host_id",
            "session_id",
            "epoch",
            "spec_hash",
            "branch",
            "baseline_sha",
            "granted_at",
        )
        expected = PROTOCOL["grant"]
        require(
            task["status"] == "running"
            and type(task["epoch"]) is int
            and task["epoch"] > 0
            and type(claim["epoch"]) is int
            and type(receipt["epoch"]) is int
            and task["spec_hash"] == PROTOCOL["spec_hash"]
            and hashlib.sha256(encoded(task["spec"])).hexdigest()
            == PROTOCOL["spec_hash"]
            and claim["epoch"] == task["epoch"]
            and claim["spec_hash"] == task["spec_hash"]
            and claim["actor"] == expected["actor"]
            and claim["host_id"] == expected["host_id"]
            and isinstance(claim["session_id"], str)
            and bool(claim["session_id"])
            and claim["baseline_sha"] == source_revision
            and receipt["status"] == "granted"
            and receipt["verb"] == "next"
            and receipt["task_id"] == str(PROTOCOL["task"])
            and receipt["epoch"] == task["epoch"]
            and receipt["actor"] == claim["actor"]
            and receipt["at"] == claim["granted_at"]
            and all(receipt["claim"].get(key) == claim[key] for key in immutable)
            and finite(receipt["claim"]["expires_at"])
            and receipt["claim"]["expires_at"] <= claim["expires_at"],
            "Missing matching committed scientific grant",
        )
        require(
            task["spec"]["resources"] == expected["resources"]
            and task["spec"]["paths"] == ["docs/AICUP_POSE_SCALING_REPORT.md"]
            and str(PROTOCOL["code_task"]) in task["spec"]["dependencies"],
            "Code-only or changed scientific scope cannot launch science",
        )
        require(
            finite(observation["at"])
            and 0 <= now - observation["at"] <= expected["observation_seconds"]
            and finite(claim["granted_at"])
            and claim["granted_at"] <= now
            and finite(claim["expires_at"])
            and claim["expires_at"] > now
            and now < claim["granted_at"] + PROTOCOL["limits"]["task_seconds"],
            "Stale, expired or future scientific grant",
        )
        require(
            not task.get("history")
            and claim["branch"].startswith(f"codex/issue-{PROTOCOL['task']}-"),
            "Recovered ownership cannot reset the one scientific task window",
        )
        require(
            code["status"] == "done"
            and code["delivery_pending"] is False
            and isinstance(code["candidate_run"], str)
            and code["candidate_run"].startswith(
                "https://github.com/Ken0u/badminton-match-analyzer/actions/runs/"
            )
            and bool(code["merge_sha"])
            and not code.get("delivery_error")
            and not code.get("integration_error"),
            "Runner requires verified main and complete public delivery",
        )
        binding = {key: claim[key] for key in immutable}
        return binding
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Malformed scientific grant observation") from error


def operation_deadline(granted_at, committed_at, now=None, forecast=None):
    """Both immutable clocks apply; a lease/output cannot create extra time."""
    now = time.time() if now is None else now
    require(
        all(finite(value) for value in (granted_at, committed_at, now))
        and granted_at <= committed_at <= now,
        "Invalid scientific commitment clock",
    )
    deadline = min(
        granted_at + PROTOCOL["limits"]["task_seconds"],
        committed_at + PROTOCOL["limits"]["operation_seconds"],
    )
    require(now < deadline, "Expired immutable scientific window")
    if forecast is not None:
        require(
            finite(forecast)
            and forecast >= 0
            and deadline - now
            >= forecast + PROTOCOL["limits"]["extra_headroom_seconds"],
            "Insufficient metadata forecast and overhead headroom",
        )
    return deadline


def metadata_cost(clocks, failed_key):
    """Cost every remaining native frame without opening any source media."""
    require(isinstance(clocks, dict) and failed_key in clocks, "Missing failed clip")
    frames = []
    for clock in clocks.values():
        count = clock.get("decoded_frames")
        require(
            type(count) is int
            and 0 < count <= PROTOCOL["limits"]["frames_per_clip"]
            and clock.get("shape") == [1280, 720],
            "Changed metadata clock dimensions or frame bound",
        )
        frames.append(count)
    require(
        len(frames) == PROTOCOL["expected"]["remaining_clips"]
        and sum(frames) == PROTOCOL["expected"]["remaining_frames"]
        and clocks[failed_key]["decoded_frames"]
        == PROTOCOL["expected"]["failed_clip_frames"],
        "Changed remaining clip/frame denominator",
    )
    visits = 2 * sum(frames) - clocks[failed_key]["decoded_frames"]
    scratch = (
        max(frames) * PROTOCOL["limits"]["record_bytes"]
        + PROTOCOL["limits"]["index_manifest_bytes"]
    )
    require(
        visits == PROTOCOL["limits"]["decoded_frame_visits"]
        and sum(frames) == PROTOCOL["limits"]["model_observations"]
        and scratch <= PROTOCOL["limits"]["scratch_bytes"],
        "Metadata costing exceeds the fixed execution bounds",
    )
    return {
        "clips": len(frames),
        "frames": sum(frames),
        "decode_visits": visits,
        "maximum_scratch_bytes": scratch,
        "native_format_or_compression_certified": False,
    }


class StageLedger:
    """Exclusive durable counts; an unfinished stage retains a bounded unknown.

    A journal is never reopened for execution. Read-only replay verifies every
    event and hash; an interrupted call cannot become a zero or a completed fit.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.stream = self.path.open("xb")
        self.previous = "0" * 64
        self.sequence = 0
        self.active = None
        self.counts = {"decoded": 0, "observed": 0, "real_fits": 0}
        self.event("created", {})

    def event(self, kind, value):
        payload = {
            "sequence": self.sequence,
            "previous": self.previous,
            "kind": kind,
            "value": value,
        }
        raw = encoded(payload)
        require(
            len(raw) + 1 <= PROTOCOL["limits"]["journal_record_bytes"],
            "Stage record exceeds metadata bound",
        )
        self.stream.write(raw + b"\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.previous = hashlib.sha256(raw).hexdigest()
        self.sequence += 1

    def begin(self, kind, key, total):
        require(self.active is None, "Previous stage remains incomplete")
        require(
            kind in ("decoded", "observed", "real_fits")
            and isinstance(key, str)
            and bool(key)
            and type(total) is int
            and total > 0,
            "Invalid stage accounting",
        )
        limit = PROTOCOL["limits"][
            {
                "decoded": "decoded_frame_visits",
                "observed": "model_observations",
                "real_fits": "real_fits",
            }[kind]
        ]
        require(self.counts[kind] + total <= limit, "Stage would exceed scientific cap")
        self.active = {"kind": kind, "key": key, "total": total, "completed": 0}
        self.event("begin", dict(self.active))

    def advance(self, completed):
        require(self.active is not None, "No active counted stage")
        require(
            type(completed) is int
            and self.active["completed"] < completed <= self.active["total"],
            "Nonmonotonic or excess stage progress",
        )
        self.event("progress", {"completed": completed})
        self.active["completed"] = completed

    def finish(self):
        require(
            self.active is not None
            and self.active["completed"] == self.active["total"],
            "Incomplete stage cannot finish",
        )
        self.event("finish", {})
        self.counts[self.active["kind"]] += self.active["total"]
        self.active = None

    def summary(self):
        lower, upper = dict(self.counts), dict(self.counts)
        if self.active is not None:
            kind = self.active["kind"]
            lower[kind] += self.active["completed"]
            upper[kind] += self.active["total"]
            # Starting the fit consumes the sole fit even if it returns no model.
            if kind == "real_fits":
                lower[kind] = upper[kind]
        old = PROTOCOL["predecessor"]
        return {
            "lower": lower,
            "upper": upper,
            "exact": {
                key: lower[key] if lower[key] == upper[key] else None for key in lower
            },
            "incomplete_stage": self.active,
            "cumulative": {
                "decoded_lower": old["decoded_frame_visits"] + lower["decoded"],
                "decoded_upper": old["decoded_frame_visits"] + upper["decoded"],
                "observed_lower": old["model_observations_lower"] + lower["observed"],
                "observed_upper": old["model_observations_upper"] + upper["observed"],
                "observed_exact": None,
                "real_fits_consumed": old["real_fits"] + upper["real_fits"],
            },
        }

    def close(self):
        self.stream.close()

    @classmethod
    def verify(cls, path):
        """Replay bounded immutable events without reopening execution."""
        ledger = cls.__new__(cls)
        ledger.active = None
        ledger.counts = {"decoded": 0, "observed": 0, "real_fits": 0}
        ledger.event = lambda *_: None
        previous, sequence, stages = "0" * 64, 0, []
        maximum = (
            PROTOCOL["limits"]["decoded_frame_visits"]
            + PROTOCOL["limits"]["model_observations"]
            + 8 * PROTOCOL["expected"]["remaining_clips"]
            + 16
        )
        with Path(path).open("rb") as stream:
            while raw := stream.readline(16385):
                require(
                    len(raw) <= 16384 and raw.endswith(b"\n") and sequence < maximum,
                    "Truncated or oversized stage journal",
                )
                event = json.loads(raw)
                require(
                    event["sequence"] == sequence
                    and event["previous"] == previous
                    and set(event) == {"sequence", "previous", "kind", "value"},
                    "Stage journal identity/hash chain changed",
                )
                kind, value = event["kind"], event["value"]
                if sequence == 0:
                    require(kind == "created" and value == {}, "Missing journal origin")
                elif kind == "begin":
                    require(
                        set(value) == {"kind", "key", "total", "completed"}
                        and value["completed"] == 0,
                        "Invalid stage start",
                    )
                    ledger.begin(value["kind"], value["key"], value["total"])
                    stages.append({key: value[key] for key in ("kind", "key", "total")})
                elif kind == "progress":
                    require(set(value) == {"completed"}, "Invalid stage progress")
                    ledger.advance(value["completed"])
                elif kind == "finish":
                    require(value == {}, "Invalid stage finish")
                    ledger.finish()
                else:
                    raise ValueError("Unexpected stage journal event")
                previous = hashlib.sha256(raw[:-1]).hexdigest()
                sequence += 1
        require(sequence > 0, "Empty stage journal")
        return {
            "summary": ledger.summary(),
            "events": sequence,
            "sha256": previous,
            "stages": stages,
        }


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


def bounded_dimensions(width, height):
    """Display orientation can swap axes without increasing source pixels."""
    return (
        type(width) is int
        and type(height) is int
        and 0 < min(width, height) <= 720
        and max(width, height) <= 1280
    )


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
            and bounded_dimensions(*dimensions),
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
            bounded_dimensions(width, height),
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
            psutil.disk_usage(os.fspath(self.directory)).free
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
            bounded_dimensions(frame.width, frame.height),
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
def decode_spool(
    video, root, times, progress, directory, run_root, check, manifest_output=None
):
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
        if manifest_output is not None:
            spool.verify_manifest()
            publish(
                manifest_output,
                {
                    "manifest_sha256": spool.manifest_sha256,
                    "manifest": read(spool.directory / "manifest.json"),
                },
            )
        success = True
    finally:
        tracking.iter_frames, court_detection.iter_frames = old_tracking, old_court
        spool.close()
        if success:
            spool.cleanup()


def source_seals():
    root = Path(__file__).resolve().parents[2]
    return scaling.code_seals() | {
        name: digest(root / name)
        for name in (
            "scripts/continue_aicup_pose_scaling.py",
            "data/manifests/aicup_pose_continuation_protocol_v1.json",
        )
    }


def admission_receipts(workspace):
    root = Path(workspace).resolve()
    return (
        root / ".cache/pose402-admission-failure-v1.json",
        root / ".cache/pose402-input-integrity-v1.json",
    )


def prior_admission(workspace):
    """Retain the source-bound zero-operation failure without resetting its clock."""
    root = Path(workspace).resolve()
    failure, integrity = (no_links(path, root) for path in admission_receipts(root))
    expected = PROTOCOL["prior_admission"]
    require(
        digest(failure) == expected["failure_sha256"]
        and digest(integrity) == expected["integrity_sha256"],
        "Changed prior zero-operation admission evidence",
    )
    value = read(failure)
    require(
        value["task"] == expected["task"]
        and value["source"] == expected["source"]
        and value["grant_at"] == expected["granted_at"]
        and value["original_task_deadline"] == expected["deadline"]
        and value["managed_exec_terminal"] is True
        and value["managed_exec_exit_code"] == 1
        and value["prospective_created"] is False
        and value["successor_claim_created"] is False
        and value["run_output_created"] is False
        and all(
            type(value[key]) is int and value[key] == 0
            for key in (
                "active_shared_store_jobs",
                "scientific_operations_started",
                "source_decode_visits",
                "model_observations",
                "real_fits",
            )
        ),
        "Prior admission is not the preserved zero-operation failure",
    )


def predecessor(workspace):
    """Verify the failed operation without reopening its consumed entry point."""
    from . import aicup_pose_dispatch_recovery as recovery

    root = Path(workspace).resolve()
    prior_admission(root)
    cache = no_links(root / ".cache", root)
    original = no_links(cache / "pose397-freeze-v1/prospective.json", root)
    require(
        digest(original) == PROTOCOL["predecessor"]["prospective_sha256"],
        "Changed original prospective",
    )
    plan = read(original)
    require(
        plan["workspace"] == str(root)
        and plan["tested_commit"] == PROTOCOL["predecessor"]["scientific_commit"]
        and plan["deadline"] == PROTOCOL["predecessor"]["original_deadline"]
        and plan["protocol"] == scaling.PROTOCOL
        and digest(scaling.execution_claim(plan))
        == PROTOCOL["predecessor"]["claim_sha256"],
        "Changed consumed predecessor source/claim/window",
    )
    output = no_links(Path(plan["output"]), root)
    require(
        output == cache / "pose397-run-v1"
        and digest(output / "failure.json") == PROTOCOL["predecessor"]["failure_sha256"]
        and not (output / "completion.json").exists()
        and not (output / "fit-start.json").exists(),
        "Predecessor is not the preserved pre-fit failure",
    )
    companion = original.parent / "dispatch-recovery-v1"
    preservation = no_links(companion / "failure-preservation.json", root)
    require(
        digest(preservation) == PROTOCOL["predecessor"]["preservation_sha256"],
        "Changed predecessor preservation proof",
    )
    proof, terminal = read(preservation), read(companion / "terminal.json")
    require(
        digest(companion / "terminal.json") == proof["terminal_sha256"]
        and terminal["terminal"] is True
        and terminal["process_state"] == "exited"
        and terminal["scientific_success"] is False
        and terminal["exit_code"] == 1
        and proof["scientific_success"] is False
        and proof["real_fits"] == 0
        and proof["decoded_frame_visits"] == 6502
        and proof["model_observations_exact"] is None
        and proof["model_observations_completed"] == 2200
        and proof["model_observations_upper_bound"] == 3251,
        "Changed predecessor terminal/counter uncertainty",
    )
    recovery.absent_process(terminal["process"])
    failed_job = proof["store_job"]
    recovery.absent_process(
        {
            "pid": failed_job["owner_pid"],
            "created_at": failed_job["owner_started"],
        }
    )
    require(
        failed_job["status"] == "failed"
        and scaling.store_job(root / "data/processed", failed_job["id"]) == failed_job,
        "Changed original failed Store job",
    )
    for path in output.rglob("*"):
        no_links(path, root)
    actual = producer.inventory(output)
    expected = {name: value["sha256"] for name, value in proof["inventory"].items()}
    require(actual == expected, "Changed preserved partial output inventory")
    for name, value in proof["inventory"].items():
        path = no_links(output / name, root)
        require(path.stat().st_size == value["bytes"], "Changed preserved output size")
    scaling.git_seals(plan["tested_commit"], plan["code"])
    return plan, output, proof


def verified_clip(directory, clip, refs, expected_clock, complete=True):
    """Reconstruct source/clock/pose/features without decoding or inference."""
    from fractions import Fraction

    directory = Path(directory)
    video, ledger, scan = (
        read(directory / name)
        for name in ("video.json", "native-clock.json", "camera.json")
    )
    times = read(directory / "data" / video["id"] / "timestamps.json")
    require(
        digest(directory / "source.mp4") == clip["media_sha256"]
        and video["sha256"] == clip["media_sha256"] == expected_clock["media_sha256"]
        and video["path"] == "source.mp4"
        and video["frame_count"] == expected_clock["decoded_frames"]
        and video["duration_s"] <= 120
        and expected_clock["shape"] == [video["source_width"], video["source_height"]]
        and abs(
            float(Fraction(*ledger["rows"][0]["relative_time"]))
            - expected_clock["first_pts"]
        )
        <= 0.00002
        and abs(
            float(Fraction(*ledger["rows"][-1]["relative_time"]))
            - expected_clock["last_pts"]
        )
        <= 0.00002,
        "Changed reused source/clock identity",
    )
    actor.validate_clocks(video, ledger, times)
    if not complete:
        require(
            not (directory / "players.json").exists()
            and not (directory / "receipt.json").exists(),
            "Failed clip unexpectedly has completed perception",
        )
        return video, ledger, scan, times
    receipt = read(directory / "receipt.json")
    actor.verify_inventory(
        directory,
        receipt["artifacts"] | {"receipt.json": digest(directory / "receipt.json")},
    )
    result = read(directory / "players.json")
    require(result["device"].startswith("cuda"), "Changed original CUDA observations")
    coverage = producer.validate_pose(result, video, times, scan, ledger)
    diagnostics = [actor.diagnose(ref, result, video) for ref in refs]
    rows = [
        scaling.feature_row(clip, ref, diagnostic, result, video, ledger)
        for ref, diagnostic in zip(refs, diagnostics, strict=True)
    ]
    require(
        diagnostics == read(directory / "diagnostics.json")
        and rows == read(directory / "features.json")
        and receipt["key"] == clip["key"]
        and receipt["frames"] == video["frame_count"]
        and receipt["references"] == len(refs)
        and receipt["weak_pairs"] == sum(row["available"] for row in rows)
        and receipt["coverage"] == coverage
        and receipt["model_frame_observations"] == video["frame_count"],
        "Reused correspondence/features/coverage do not reproduce",
    )
    return rows, receipt


def continuation_inputs(workspace):
    plan, old_output, proof = predecessor(workspace)
    observations, diagnostics, old_rows = scaling.original_inputs(plan)
    require(
        learning.extract(observations, diagnostics, Path(plan["prepared"])) == old_rows,
        "Original pilot features do not independently reconstruct",
    )
    sources = scaling.input_sources(plan)
    clips, groups = read(sources["clips"]), read(sources["groups"])
    folds, contexts = producer.capture_folds(clips, groups)
    cohort = scaling.select_cohort(
        clips,
        folds,
        contexts,
        read(Path(plan["prepared"]) / "freeze.json"),
    )
    require(cohort == plan["cohort"], "Changed original cohort membership")
    cohort["reference_rows"] = scaling.canonical_reference_rows(
        sources["archive"],
        clips,
        folds,
        cohort,
    )
    require(
        cohort == read(old_output / "cohort.json"), "Changed original reference rows"
    )
    clocks = scaling.clock_index(plan["clock_ledger"], cohort["new_keys"])
    by_key = {clip["key"]: clip for clip in cohort["clips"]}
    reused, receipts = [], []
    require(len(proof["completed"]) == 4, "Changed completed clip denominator")
    for number, item in enumerate(proof["completed"]):
        key = cohort["new_keys"][number]
        folder = old_output / f"clip-{number:03d}"
        require(
            item["ordinal"] == number
            and digest(folder / "receipt.json") == item["receipt_sha256"],
            "Changed sealed completed clip receipt",
        )
        rows, receipt = verified_clip(
            folder,
            by_key[key],
            [r for r in cohort["reference_rows"] if r["clip_key"] == key],
            clocks[key],
        )
        require(
            receipt["decoded_frame_visits"] == 2 * receipt["frames"],
            "Changed original completed decode denominator",
        )
        reused.extend(rows)
        receipts.append(receipt)
    failed_key = cohort["new_keys"][4]
    verified_clip(
        old_output / "clip-004", by_key[failed_key], [], clocks[failed_key], False
    )
    remaining = {key: clocks[key] for key in cohort["new_keys"][4:]}
    cost = metadata_cost(remaining, failed_key)
    require(
        len(old_rows) + len(reused) == PROTOCOL["expected"]["all_features_reused"]
        and len(cohort["clips"]) == PROTOCOL["expected"]["all_clips"]
        and len(cohort["reference_rows"]) == PROTOCOL["expected"]["all_reference_rows"]
        and sum(row["fold"] == "validation" for row in old_rows)
        == PROTOCOL["expected"]["validation_rows"],
        "Changed complete source/reference/validation denominator",
    )
    return plan, cohort, clocks, old_rows, reused, receipts, cost


def claim_path(workspace):
    return (
        Path(workspace)
        / ".cache"
        / (
            PROTOCOL["name"]
            + "-"
            + scaling.PROTOCOL["sources"]["archive"]
            + "-start.json"
        )
    )


def owned_output(workspace, path):
    path = actor.private_output(workspace, path)
    no_links(path, Path(workspace).resolve())
    return path


def retained_roots(plan):
    original = plan["original"]
    root = Path(plan["workspace"])
    return (
        {Path(original[key]) for key in ("prepared", "native", "audit", "control")}
        | {
            Path(original[key]).parent
            for key in ("actor_prospective", "control_prospective")
        }
        | {
            Path(original["output"]),
            Path(original["prospective_directory"]),
            Path(plan["prospective_directory"]),
            Path(plan["output"]),
            *admission_receipts(root),
            root / ".cache/pose402-observations",
            root / ".cache/pose405-observations",
        }
    )


def disk_budget(plan, reserve=0, scratch_reserve=0):
    """Measure all retained attempts plus the one active owned scratch spool."""
    import psutil

    require(
        all(type(value) is int and value >= 0 for value in (reserve, scratch_reserve)),
        "Invalid disk reservation",
    )
    files = {}
    root = Path(plan["workspace"])
    for folder in retained_roots(plan):
        no_links(folder, root)
        if folder.is_file():
            files[folder] = folder.stat().st_size
        elif folder.exists():
            for path in folder.rglob("*"):
                no_links(path, root)
                if path.is_file():
                    files[path] = path.stat().st_size
    scratch_root = Path(plan["output"]) / "scratch"
    scratch = sum(
        size for path, size in files.items() if path.is_relative_to(scratch_root)
    )
    retained = sum(files.values()) - scratch
    # A failed spool stays retained as well as counting toward combined usage.
    if (Path(plan["output"]) / "failure.json").exists():
        retained += scratch
    require(
        scratch + scratch_reserve <= PROTOCOL["limits"]["scratch_bytes"]
        and retained + reserve <= PROTOCOL["limits"]["retained_bytes"]
        and sum(files.values()) + reserve + scratch_reserve
        <= PROTOCOL["limits"]["combined_bytes"]
        and psutil.disk_usage(os.fspath(root)).free
        >= reserve + scratch_reserve + PROTOCOL["limits"]["minimum_disk_free_bytes"],
        "Continuation retained/scratch/combined disk budget exceeded",
    )
    return {
        "retained_bytes": retained,
        "scratch_bytes": scratch,
        "combined_bytes": sum(files.values()),
    }


def terminal_record(path, value, create=False):
    data = encoded(value)
    size = PROTOCOL["limits"]["terminal_bytes"]
    require(len(data) <= size, "Terminal metadata exceeds reserved slot")
    with Path(path).open("xb" if create else "r+b") as stream:
        if not create:
            require(
                os.fstat(stream.fileno()).st_size == size,
                "Changed terminal reservation",
            )
        stream.write(data.ljust(size, b" "))
        stream.flush()
        os.fsync(stream.fileno())


def preserve_failure(output, ledger, error):
    """Best-effort diagnostics must never replace the caller's primary error.

    The terminal slot was reserved before work. All other writes still pass
    through the scoped RAM/disk admission, even while handling an exception.
    Avoid invoking arbitrary exception formatting or copying an unbounded
    message into a diagnostic artifact.
    """
    reporting_errors = []

    def attempt(stage, operation):
        try:
            return operation()
        except BaseException as secondary:
            reporting_errors.append(
                {"stage": stage, "error_type": type(secondary).__name__[:128]}
            )
            return None

    arguments = BaseException.args.__get__(error)
    plain_message = len(arguments) == 1 and type(arguments[0]) is str
    message = (
        arguments[0][:1024]
        if plain_message
        else "Message omitted: exception has no single plain string argument"
    )
    record = {
        "terminal": True,
        "scientific_success": False,
        "error_type": type(error).__name__[:128],
        "message": message,
        "message_truncated": not plain_message or len(arguments[0]) > 1024,
        "accounting": attempt("accounting", ledger.summary) if ledger else None,
    }
    if ledger is not None:
        attempt("journal_close", ledger.close)

    def save_terminal():
        path = output / "terminal.json"
        if path.exists():
            no_links(path, output)
            terminal_record(path, {**record, "reporting_errors": reporting_errors})

    attempt("terminal", save_terminal)

    def save_failure():
        path = output / "failure.json"
        if output.exists() and not path.exists():
            publish(
                path,
                {
                    **record,
                    "at": time.time(),
                    "successor_consumed": True,
                    "reporting_errors": reporting_errors,
                },
            )

    attempt("failure_json", save_failure)
    if reporting_errors:
        # One bounded update records secondary failures in already reserved
        # bytes. There is no retry of ordinary artifact publication.
        attempt("terminal_diagnostics", save_terminal)
        try:
            for diagnostic in reporting_errors:
                sys.stderr.write(
                    "Continuation failure reporting: "
                    f"{diagnostic['stage']} ({diagnostic['error_type']})\n"
                )
        except BaseException:
            pass  # Even stderr may be unavailable during the primary failure.


class OutputBudget:
    """Reserve future journal/terminal bytes and admit opaque artifact writers.

    Scratch checks stat only the single active spool. Historical retained bytes
    are remeasured before each artifact write, avoiding a full tree scan for
    every cached player/court frame read.
    """

    def __init__(self, plan):
        self.plan = plan
        self.output = Path(plan["output"])
        maximum_events = (
            PROTOCOL["limits"]["decoded_frame_visits"]
            + PROTOCOL["limits"]["model_observations"]
            + 8 * PROTOCOL["expected"]["remaining_clips"]
            + 16
        )
        self.journal_reserve = (
            maximum_events * PROTOCOL["limits"]["journal_record_bytes"]
        )
        self.retained = 0
        self.refresh()

    def refresh(self, reserve=0):
        result = disk_budget(self.plan, reserve + self.journal_reserve)
        self.retained = result["retained_bytes"]
        return result

    def scratch(self, reserve=0):
        import psutil

        scratch = self.output / "scratch"
        size = 0
        if scratch.exists():
            for path in scratch.rglob("*"):
                no_links(path, self.output)
                if path.is_file():
                    size += path.stat().st_size
        require(
            size + reserve <= PROTOCOL["limits"]["scratch_bytes"]
            # The failed spool must also fit the retained-evidence allowance.
            and self.retained + self.journal_reserve + size + reserve
            <= PROTOCOL["limits"]["retained_bytes"]
            and psutil.disk_usage(os.fspath(self.output)).free
            >= reserve + PROTOCOL["limits"]["minimum_disk_free_bytes"],
            "Active spool would exceed preservable disk allowance",
        )


@contextmanager
def bounded_outputs(plan, budget):
    """Scope byte admission around unchanged JSON and checkpoint producers."""
    import psutil

    from . import tracking

    original_publish = publish
    old_publishers = (
        producer.publish,
        learning.publish,
        tracking.write_json,
        learning.save_state,
    )

    def admit(path, value, writer, tracking_json=False):
        no_links(Path(path), Path(plan["output"]))
        encoder = (
            json.JSONEncoder()
            if tracking_json
            else json.JSONEncoder(
                sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        )
        size = sum(len(chunk.encode("utf-8")) for chunk in encoder.iterencode(value))
        require(
            psutil.virtual_memory().available
            >= PROTOCOL["limits"]["minimum_ram_free_bytes"] + 2 * size,
            "Insufficient JSON serialization RAM reserve",
        )
        budget.refresh(size)
        result = writer(path, value)
        budget.refresh()
        return result

    def checked_publish(path, value):
        return admit(path, value, original_publish)

    def checked_json(path, value):
        return admit(path, value, old_publishers[2], tracking_json=True)

    def checked_state(path, model):
        no_links(Path(path), Path(plan["output"]))
        size = sum(
            tensor.numel() * tensor.element_size()
            for tensor in model.state_dict().values()
        )
        reserve = 2 * size + 1024 * 1024
        budget.refresh(reserve)
        result = old_publishers[3](path, model)
        require(
            Path(path).stat().st_size <= reserve,
            "Unexpected checkpoint serialization size",
        )
        budget.refresh()
        return result

    global_publishers = globals()
    try:
        global_publishers["publish"] = producer.publish = learning.publish = (
            checked_publish
        )
        tracking.write_json = checked_json
        learning.save_state = checked_state
        yield
    finally:
        global_publishers["publish"] = original_publish
        producer.publish, learning.publish, tracking.write_json, learning.save_state = (
            old_publishers
        )


def freeze(workspace, grant_state, protocol, output, run_output):
    """Metadata/integrity only; the separately granted science owns this freeze."""
    require(read(protocol) == PROTOCOL, "Changed fixed continuation protocol")
    root = Path(workspace).resolve()
    code = source_seals()
    revision = scaling.tested_commit()
    scaling.git_seals(revision, code)
    grant = live_grant(read(grant_state), revision)
    committed_at = time.time()
    deadline = operation_deadline(
        grant["granted_at"],
        committed_at,
        forecast=PROTOCOL["limits"]["minimum_forecast_seconds"],
    )
    original, cohort, _clocks, old_rows, reused, receipts, cost = continuation_inputs(
        root
    )
    require(
        original["runtime"] == producer.runtime(), "Changed original native runtime"
    )
    prospective_directory = owned_output(root, output)
    run_output = owned_output(root, run_output)
    protected = {
        Path(original[key]).resolve()
        for key in (
            "prepared",
            "native",
            "audit",
            "control",
            "output",
            "prospective_directory",
        )
    }
    for path in (prospective_directory, run_output):
        require(
            not path.exists()
            and not any(
                path.is_relative_to(p) or p.is_relative_to(path) for p in protected
            ),
            "Preserve original or already used continuation outputs",
        )
    require(
        not prospective_directory.is_relative_to(run_output)
        and not run_output.is_relative_to(prospective_directory)
        and not claim_path(root).exists(),
        "Continuation paths overlap or successor already consumed",
    )
    plan = {
        "workspace": str(root),
        "original": original,
        "prospective_directory": str(prospective_directory),
        "output": str(run_output),
        "protocol": PROTOCOL,
        "code": code,
        "tested_commit": revision,
        "runtime": producer.runtime(),
        "grant": grant,
        "committed_at": committed_at,
        "deadline": deadline,
        "cohort": cohort,
        "cost": cost,
        "reused_rows_sha256": hashlib.sha256(encoded(old_rows + reused)).hexdigest(),
        "reused_receipts_sha256": hashlib.sha256(encoded(receipts)).hexdigest(),
    }
    require(
        live_grant(read(grant_state), revision) == grant, "Ownership changed in freeze"
    )
    require(source_seals() == code, "Consumer changed during freeze")
    operation_deadline(
        grant["granted_at"],
        committed_at,
        forecast=PROTOCOL["limits"]["minimum_forecast_seconds"],
    )
    disk_budget(plan, scratch_reserve=cost["maximum_scratch_bytes"])
    prospective_directory.mkdir(exist_ok=False)
    publish(prospective_directory / "prospective.json", plan)
    expected = digest(prospective_directory / "prospective.json")
    publish(
        claim_path(root),
        {
            "prospective_sha256": expected,
            "output": str(run_output),
            "committed_at": committed_at,
            "deadline": deadline,
        },
    )
    return {
        "prospective_sha256": expected,
        "execution_claim_sha256": digest(claim_path(root)),
        "new_decodes": 0,
        "new_model_observations": 0,
        "real_fits": 0,
    }


def prospective(path, expected, grant_state=None, clock=False):
    require(digest(path) == expected, "Changed continuation prospective seal")
    plan = read(path)
    require(
        plan["protocol"] == PROTOCOL
        and plan["code"] == source_seals()
        and plan["runtime"] == producer.runtime(),
        "Changed frozen continuation source/runtime/protocol",
    )
    scaling.git_seals(plan["tested_commit"], plan["code"])
    require(
        read(claim_path(plan["workspace"]))
        == {
            "prospective_sha256": expected,
            "output": plan["output"],
            "committed_at": plan["committed_at"],
            "deadline": plan["deadline"],
        },
        "Changed exclusive successor execution claim",
    )
    if clock:
        grant = live_grant(read(grant_state), plan["tested_commit"])
        require(grant == plan["grant"], "Changed scientific task ownership")
        require(
            operation_deadline(grant["granted_at"], plan["committed_at"])
            == plan["deadline"],
            "Changed immutable scientific deadline",
        )
    return plan


@contextmanager
def observed_model(ledger, key, frames, check):
    __import__("torchvision")  # initialize before threaded PyAV
    from ultralytics import YOLO

    original = YOLO.predict
    ledger.begin("observed", key, frames)

    def predict(model, *args, **kwargs):
        check()
        require(ledger.active["completed"] < frames, "Excess model observation")
        result = original(model, *args, **kwargs)
        ledger.advance(ledger.active["completed"] + 1)
        return result

    try:
        YOLO.predict = predict
        yield
        ledger.finish()
    finally:
        YOLO.predict = original


def continue_clip(
    plan, clip, refs, clock, directory, ledger, check, progress, reuse=None
):
    """Exactly one remaining perception decode; preparation is never replayed."""
    import torchvision  # noqa: F401

    from .schemas import empty_annotations
    from .tracking import track_players

    directory.mkdir(exist_ok=False)
    media, expected = directory / "source.mp4", clock["decoded_frames"]
    if reuse is not None:
        video, source_clock, scan, times = verified_clip(reuse, clip, [], clock, False)
        # Copy already verified bytes; this is not another decoder pass.
        with (
            (Path(reuse) / "source.mp4").open("rb") as source,
            media.open("xb") as target,
        ):
            for block in iter(lambda: source.read(1024 * 1024), b""):
                check(reserve=len(block))
                target.write(block)
        publish(
            directory / "preparation-reuse.json",
            {
                "source": str(reuse),
                "source_sha256": clip["media_sha256"],
                "frames": expected,
                "new_preparation_decodes": 0,
            },
        )
    else:
        with zipfile.ZipFile(plan["original"]["sources"]["archive"]["path"]) as archive:
            info = archive.getinfo(clip["media_path"])
            require(
                info.file_size == clip["media_bytes"], "Changed archive member size"
            )
            with archive.open(info) as source, media.open("xb") as target:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    check(reserve=len(block))
                    target.write(block)
        require(digest(media) == clip["media_sha256"], "Changed source bytes")
        publish(
            directory / "preparation-start.json",
            {"frames": expected, "key": clip["key"]},
        )
        ledger.begin("decoded", clip["key"] + ":preparation", expected)

        def preparation(index):
            check()
            ledger.advance(index + 1)

        source_clock, times, video, scan = scaling.clock_and_scan(media, preparation)
        ledger.finish()
    require(digest(media) == clip["media_sha256"], "Changed copied native source")
    video = dict(video, path="source.mp4")
    publish(directory / "native-clock.json", source_clock)
    publish(directory / "video.json", video)
    publish(directory / "camera.json", scan)
    data = directory / "data"
    (data / video["id"]).mkdir(parents=True)
    publish(data / video["id"] / "timestamps.json", times)
    # Check the actual prepared clock before any perception or source replay.
    verified_clip(directory, clip, [], clock, False)
    publish(
        directory / "perception-start.json",
        {"frames": expected, "key": clip["key"], "passes": 1},
    )
    ledger.begin("decoded", clip["key"] + ":perception", expected)

    def decoded(count):
        check()
        ledger.advance(count)

    scratch = Path(plan["output"]) / "scratch"
    scratch.mkdir(exist_ok=True)
    with decode_spool(
        video,
        directory,
        times,
        decoded,
        scratch / directory.name,
        Path(plan["output"]),
        lambda reserve=0: check(scratch_reserve=reserve),
        directory / "pixel-spool.json",
    ) as count:
        require(count == expected, "Changed native source coverage")
        ledger.finish()
        with (
            observed_model(ledger, clip["key"], expected, check),
            scaling.required_cuda(),
        ):
            track_players(
                video,
                directory,
                data,
                empty_annotations("singles"),
                0,
                expected,
                1,
                progress,
                directory / "players.json",
                player_model="small",
                auto_calibrate=True,
                camera_scan=scan,
            )
    result = read(directory / "players.json")
    require(result["device"].startswith("cuda"), "CPU fallback is forbidden")
    coverage = producer.validate_pose(result, video, times, scan, source_clock)
    diagnostics = [actor.diagnose(ref, result, video) for ref in refs]
    features = [
        scaling.feature_row(clip, ref, diagnostic, result, video, source_clock)
        for ref, diagnostic in zip(refs, diagnostics, strict=True)
    ]
    publish(directory / "diagnostics.json", diagnostics)
    publish(directory / "features.json", features)
    receipt = {
        "key": clip["key"],
        "frames": expected,
        "references": len(refs),
        "weak_pairs": sum(row["available"] for row in features),
        "coverage": coverage,
        "decoded_frame_visits": expected * (1 if reuse is not None else 2),
        "model_frame_observations": expected,
        "preparation_reused": reuse is not None,
        "artifacts": producer.inventory(directory),
    }
    publish(directory / "receipt.json", receipt)
    check(full=True)
    return features, receipt


def published_intent(value, plan, expected):
    require(
        value.get("author") == plan["grant"]["actor"]
        and isinstance(value.get("url"), str)
        and value["url"].startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/405#issuecomment-"
        )
        and value.get("intent")
        == {
            "task": PROTOCOL["task"],
            "spec_hash": PROTOCOL["spec_hash"],
            "prospective_sha256": expected,
            "source_commit": plan["tested_commit"],
        }
        and finite(value.get("published_at"))
        and plan["committed_at"] <= value["published_at"] <= time.time(),
        "Missing exact prospectively published scientific intent",
    )


def run(prospective_path, prospective_sha256, output, grant_state, publication):
    plan = prospective(prospective_path, prospective_sha256, grant_state, True)
    intent = read(publication)
    published_intent(intent, plan, prospective_sha256)
    output = owned_output(plan["workspace"], output)
    require(
        str(output) == plan["output"] and not output.exists(),
        "Preserve previously used or mismatched continuation output",
    )
    require(
        operation_deadline(
            plan["grant"]["granted_at"],
            plan["committed_at"],
            forecast=PROTOCOL["limits"]["minimum_forecast_seconds"],
        )
        == plan["deadline"],
        "Changed admission window",
    )
    import torch

    require(
        torch.cuda.is_available(), "Original CUDA runtime is required; no CPU fallback"
    )
    original, cohort, clocks, old_rows, reused, old_receipts, cost = (
        continuation_inputs(plan["workspace"])
    )
    require(
        original == plan["original"]
        and cohort == plan["cohort"]
        and cost == plan["cost"]
        and hashlib.sha256(encoded(old_rows + reused)).hexdigest()
        == plan["reused_rows_sha256"]
        and hashlib.sha256(encoded(old_receipts)).hexdigest()
        == plan["reused_receipts_sha256"],
        "Changed prospectively frozen continuation inputs",
    )
    root, data, _ = producer.configure_workspace(plan["workspace"])
    learning.validate_workspace(original)
    import psutil
    import torchvision  # noqa: F401

    from .jobs import run_local_job
    from .storage import Store

    annotations = producer.annotation_snapshot(data)
    store = Store(data)
    ledger, receipts = None, list(old_receipts)
    output_budget = OutputBudget(plan)

    def task(job_id, progress):
        nonlocal ledger
        # Occupied shared-Store admission refuses before creating a run output.
        prospective(prospective_path, prospective_sha256, grant_state, True)
        output.mkdir(exist_ok=False)
        terminal_record(
            output / "terminal.json",
            {"terminal": False, "scientific_success": False},
            create=True,
        )
        process = psutil.Process()
        publish(
            output / "process.json",
            {
                "job_id": job_id,
                "pid": process.pid,
                "created_at": process.create_time(),
                "cwd": str(Path.cwd()),
                "command": process.cmdline(),
                "prospective_sha256": prospective_sha256,
            },
        )
        publish(
            output / "dispatch.json",
            {
                "prospective_sha256": prospective_sha256,
                "publication_sha256": hashlib.sha256(encoded(intent)).hexdigest(),
                "started_at": time.time(),
            },
        )
        publish(output / "publication.json", intent)
        publish(output / "cohort.json", cohort)
        ledger = StageLedger(output / "stages.jsonl")
        fresh = list(reused)
        by_key = {clip["key"]: clip for clip in cohort["clips"]}
        last_disk = 0.0

        def check(reserve=0, scratch_reserve=0, full=False):
            nonlocal last_disk
            require(
                operation_deadline(plan["grant"]["granted_at"], plan["committed_at"])
                == plan["deadline"],
                "Changed scientific window",
            )
            require(
                psutil.virtual_memory().available
                >= PROTOCOL["limits"]["minimum_ram_free_bytes"],
                "Insufficient live RAM safety reserve",
            )
            now = time.monotonic()
            if scratch_reserve:
                output_budget.scratch(scratch_reserve)
            if full or reserve or now - last_disk >= 5:
                output_budget.refresh(reserve)
                last_disk = now

        for number, key in enumerate(cohort["new_keys"][4:], 4):
            prospective(prospective_path, prospective_sha256, grant_state, True)
            check(full=True)
            rows, receipt = continue_clip(
                plan,
                by_key[key],
                [row for row in cohort["reference_rows"] if row["clip_key"] == key],
                clocks[key],
                output / f"clip-{number:03d}",
                ledger,
                check,
                lambda value: progress(0.9 * (number - 4 + value) / len(clocks)),
                Path(original["output"]) / "clip-004" if number == 4 else None,
            )
            fresh.extend(rows)
            receipts.append(receipt)
            publish(output / f"progress-{number:03d}.json", ledger.summary())
        require(
            ledger.summary()["exact"]
            == {
                "decoded": PROTOCOL["limits"]["decoded_frame_visits"],
                "observed": PROTOCOL["limits"]["model_observations"],
                "real_fits": 0,
            },
            "Incomplete remaining native execution denominator",
        )
        rows = scaling.combined_features(cohort, old_rows, fresh)
        require(
            len(rows) == PROTOCOL["expected"]["all_reference_rows"],
            "Incomplete full row denominator",
        )
        publish(output / "features.json", rows)
        ledger.begin("real_fits", "candidate", 1)
        publish(
            output / "fit-start.json",
            {"real_fits": 1, "training": scaling.PROTOCOL["training"]},
        )

        def report(epoch, checkpoint):
            check(full=checkpoint)
            if checkpoint:
                prospective(prospective_path, prospective_sha256, grant_state, True)
            progress(0.9 + 0.1 * epoch / scaling.PROTOCOL["training"]["epochs"])

        result = learning.fit(
            learning.arrays(rows, "static"), output / "candidate", report
        )
        ledger.advance(1)
        ledger.finish()
        control = Path(original["control"]) / "static"
        report = scaling.comparison(
            rows,
            result,
            read(output / "candidate/predictions.json"),
            old_rows,
            read(control / "result.json"),
            read(control / "predictions.json"),
        )
        publish(output / "report.json", report)
        continuation_inputs(root)
        require(
            producer.annotation_snapshot(data) == annotations,
            "Original application truth changed",
        )
        check(full=True)
        return {
            "references": len(rows),
            "remaining_clips": len(receipts) - 4,
            "accounting": ledger.summary(),
            "prospective_sha256": prospective_sha256,
        }

    writers = bounded_outputs(plan, output_budget)
    writers.__enter__()
    try:
        summary = run_local_job(store, "feature-preparation", None, task)
        process = read(output / "process.json")
        job = store.job(process["job_id"])
        require(
            job["status"] == "completed" and job["summary"] == summary,
            "Missing durable shared Store completion",
        )
        ledger.close()
        require(
            StageLedger.verify(output / "stages.jsonl")["summary"]
            == summary["accounting"],
            "Durable stage accounting does not reproduce",
        )
        terminal_record(
            output / "terminal.json",
            {
                "terminal": True,
                "scientific_success": True,
                "accounting": summary["accounting"],
            },
        )
        completion = {
            "summary": summary,
            "receipts": receipts,
            "job_id": job["id"],
            "shared_data": str(data),
            "execution_claim": str(claim_path(root)),
            "prospective_sha256": prospective_sha256,
            "finished_at": time.time(),
            "original_annotations_sha256": annotations,
            "artifacts": producer.inventory(output),
            "training_ready": False,
            "model_installed_in_app": False,
            "test_opened": False,
        }
        prospective(prospective_path, prospective_sha256, grant_state, True)
        disk_budget(plan, len(encoded(completion)))
        publish(output / "completion.json", completion)
        return summary
    except BaseException as error:
        output_budget.journal_reserve = 0
        try:
            preserve_failure(output, ledger, error)
        except BaseException:
            pass  # Catastrophic diagnostic allocation must not mask the cause.
        raise
    finally:
        writers.__exit__(None, None, None)


def verify(prospective_path, prospective_sha256, output):
    """Reconstruct all rows and checkpoints without decode, inference or fit."""
    plan = prospective(prospective_path, prospective_sha256)
    output = owned_output(plan["workspace"], output)
    require(
        str(output) == plan["output"] and not (output / "failure.json").exists(),
        "Cannot verify a failed or different continuation output",
    )
    complete = read(output / "completion.json")
    terminal = read(output / "terminal.json")
    require(
        terminal["terminal"] is True and terminal["scientific_success"] is True,
        "Missing successful reserved terminal evidence",
    )
    deadline = min(
        plan["grant"]["granted_at"] + PROTOCOL["limits"]["task_seconds"],
        plan["committed_at"] + PROTOCOL["limits"]["operation_seconds"],
    )
    require(
        complete["prospective_sha256"] == prospective_sha256
        and complete["execution_claim"] == str(claim_path(plan["workspace"]))
        and complete["shared_data"] == str(Path(plan["workspace"]) / "data/processed")
        and finite(complete["finished_at"])
        and plan["committed_at"]
        <= complete["finished_at"]
        < deadline
        == plan["deadline"]
        and complete["training_ready"] is False
        and complete["model_installed_in_app"] is False
        and complete["test_opened"] is False,
        "Changed continuation execution window, ownership or truth flags",
    )
    actor.verify_inventory(
        output,
        complete["artifacts"]
        | {
            "completion.json": digest(output / "completion.json"),
        },
    )
    intent, dispatch = read(output / "publication.json"), read(output / "dispatch.json")
    published_intent(intent, plan, prospective_sha256)
    require(
        dispatch["prospective_sha256"] == prospective_sha256
        and dispatch["publication_sha256"]
        == hashlib.sha256(encoded(intent)).hexdigest()
        and plan["committed_at"]
        <= intent["published_at"]
        <= dispatch["started_at"]
        <= complete["finished_at"],
        "Changed prospectively published dispatch binding",
    )
    original, cohort, clocks, old_rows, reused, old_receipts, cost = (
        continuation_inputs(plan["workspace"])
    )
    require(
        original == plan["original"]
        and cohort == plan["cohort"]
        and cohort == read(output / "cohort.json")
        and cost == plan["cost"],
        "Changed complete continuation source/cohort/cost",
    )
    fresh, receipts, stages = list(reused), list(old_receipts), []
    by_key = {clip["key"]: clip for clip in cohort["clips"]}
    for number, key in enumerate(cohort["new_keys"][4:], 4):
        folder, count = output / f"clip-{number:03d}", clocks[key]["decoded_frames"]
        refs = [row for row in cohort["reference_rows"] if row["clip_key"] == key]
        rows, receipt = verified_clip(folder, by_key[key], refs, clocks[key])
        require(
            receipt["preparation_reused"] is (number == 4)
            and receipt["decoded_frame_visits"] == count * (1 if number == 4 else 2)
            and read(folder / "perception-start.json")
            == {"frames": count, "key": key, "passes": 1},
            "Changed continuation source-pass/reuse count",
        )
        if number == 4:
            require(
                read(folder / "preparation-reuse.json")
                == {
                    "source": str(Path(original["output"]) / "clip-004"),
                    "source_sha256": by_key[key]["media_sha256"],
                    "frames": count,
                    "new_preparation_decodes": 0,
                },
                "Changed failed-clip preparation reuse",
            )
            require(
                not (folder / "preparation-start.json").exists(),
                "Failed preparation was replayed",
            )
        else:
            require(
                read(folder / "preparation-start.json")
                == {"frames": count, "key": key},
                "Changed single preparation dispatch",
            )
            stages.append(
                {"kind": "decoded", "key": key + ":preparation", "total": count}
            )
        stages.extend(
            [
                {"kind": "decoded", "key": key + ":perception", "total": count},
                {"kind": "observed", "key": key, "total": count},
            ]
        )
        pixels = read(folder / "pixel-spool.json")
        require(
            hashlib.sha256(encoded(pixels["manifest"])).hexdigest()
            == pixels["manifest_sha256"]
            and pixels["manifest"]["frames"] == count
            and len(pixels["manifest"]["entries"]) == count
            and not (output / "scratch" / folder.name).exists(),
            "Changed successful spool manifest or missing cleanup",
        )
        fresh.extend(rows)
        receipts.append(receipt)
    stages.append({"kind": "real_fits", "key": "candidate", "total": 1})
    accounting = StageLedger.verify(output / "stages.jsonl")
    require(
        accounting["stages"] == stages
        and accounting["summary"]["incomplete_stage"] is None
        and accounting["summary"]["exact"]
        == {
            "decoded": PROTOCOL["limits"]["decoded_frame_visits"],
            "observed": PROTOCOL["limits"]["model_observations"],
            "real_fits": 1,
        },
        "Full durable execution order/denominator does not reproduce",
    )
    rows = scaling.combined_features(cohort, old_rows, fresh)
    require(
        rows == read(output / "features.json") and receipts == complete["receipts"],
        "Full original/new feature denominator changed",
    )
    result, predictions = learning.verify_arm(
        learning.arrays(rows, "static"), output / "candidate"
    )
    control, control_predictions = learning.verify_arm(
        learning.arrays(old_rows, "static"), Path(original["control"]) / "static"
    )
    report = scaling.comparison(
        rows, result, predictions, old_rows, control, control_predictions
    )
    require(
        report == read(output / "report.json"), "Fixed comparison does not reproduce"
    )
    expected = {
        "references": len(rows),
        "remaining_clips": len(receipts) - 4,
        "accounting": accounting["summary"],
        "prospective_sha256": prospective_sha256,
    }
    job = scaling.store_job(complete["shared_data"], complete["job_id"])
    require(
        complete["summary"] == expected
        and terminal["accounting"] == expected["accounting"]
        and job.get("status") == "completed"
        and job.get("summary") == expected
        and read(output / "fit-start.json")
        == {"real_fits": 1, "training": scaling.PROTOCOL["training"]}
        and producer.annotation_snapshot(complete["shared_data"])
        == complete["original_annotations_sha256"],
        "Changed durable shared Store/fit/annotation completion",
    )
    disk_budget(plan)
    return {
        "verified_references": len(rows),
        "validation_rows": PROTOCOL["expected"]["validation_rows"],
        "remaining_native_clips": len(receipts) - 4,
        "accounting": accounting["summary"],
        "verification_new_decodes": 0,
        "verification_model_observations": 0,
        "verification_real_fits": 0,
        "independent_accuracy_established": False,
        "model_installed_in_app": False,
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("freeze")
    for name in ("workspace", "grant-state", "protocol", "output", "run-output"):
        prepare.add_argument("--" + name, type=Path, required=True)
    for action in ("run", "verify"):
        command = commands.add_parser(action)
        command.add_argument("--prospective", type=Path, required=True)
        command.add_argument("--prospective-sha256", required=True)
        command.add_argument("--output", type=Path, required=True)
        if action == "run":
            command.add_argument("--grant-state", type=Path, required=True)
            command.add_argument("--publication", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    action = args.pop("command")
    if action == "freeze":
        result = freeze(**args)
    else:
        args["prospective_path"] = args.pop("prospective")
        result = (run if action == "run" else verify)(**args)
    print(json.dumps(result, indent=2, allow_nan=False))
