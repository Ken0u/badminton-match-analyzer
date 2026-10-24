"""Pure metadata rules for a prospectively frozen, single-attempt recovery.

No scientific labels, media, process signals or transport are accessed here.
An archived failed reference never becomes part of the accepted prefix.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from pathlib import Path


def opaque_inventory(root):
    """Seal every archived file without parsing its scientific contents."""
    root = Path(root)
    rows = []
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            node = Path(folder) / name
            info = node.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 1024
            ):
                raise ValueError("Archived evidence must not traverse links")
        for name in files:
            node = Path(folder) / name
            result = hashlib.sha256()
            with node.open("rb") as handle:
                for part in iter(lambda: handle.read(1024 * 1024), b""):
                    result.update(part)
            rows.append(
                (
                    node.relative_to(root).as_posix(),
                    node.stat().st_size,
                    result.hexdigest(),
                )
            )
    if not rows:
        raise ValueError("Archived evidence inventory is empty")
    raw = json.dumps(sorted(rows), separators=(",", ":")).encode("utf-8")
    return {"files": len(rows), "sha256": hashlib.sha256(raw).hexdigest()}


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Expected an exact bounded integer")
    return value


def deadline(granted_at, inherited_deadline, *, now):
    granted_at = integer(granted_at)
    inherited_deadline = integer(inherited_deadline)
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError("Expected a finite observation time")
    end = min(granted_at + 8 * 3600, inherited_deadline)
    if not granted_at <= now < end - 60:
        raise ValueError("Recovery dispatch interval is not open")
    return end


def key(row, ordinal):
    source = row.get("source_id")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Expected a source identifier")
    return source, integer(row[ordinal])


def membership(row):
    frames = [integer(n) for n in row["frames"]]
    if not frames or len(set(frames)) != len(frames):
        raise ValueError("Empty or duplicate native membership")
    return frames


def partition(chunks, prefix, suffix):
    """Require an exact disjoint partition, preserving order and native images."""
    planned = {key(row, "index"): row for row in chunks}
    if not planned or len(planned) != len(chunks):
        raise ValueError("Duplicate or empty target plan")
    accepted = [key(row, "chunk") for row in prefix]
    remaining = [key(row, "index") for row in suffix]
    if (
        len(set(accepted)) != len(accepted)
        or len(set(remaining)) != len(remaining)
        or set(accepted) & set(remaining)
        or set(accepted) | set(remaining) != set(planned)
        or accepted != [item for item in planned if item in set(accepted)]
        or remaining != [item for item in planned if item in set(remaining)]
    ):
        raise ValueError("Recovery prefix and suffix must partition the exact plan")
    for row in prefix:
        if membership(row) != membership(planned[key(row, "chunk")]):
            raise ValueError("Archived prefix native membership changed")
    for row in suffix:
        expected = planned[key(row, "index")]
        if row != expected:
            raise ValueError("Recovery suffix differs from the original plan")
    return True


def recovery_cost(prior_bytes, suffix, *, limit=8 * 1024**3):
    total = integer(prior_bytes)
    seen = set()
    for row in suffix:
        item = key(row, "index")
        if item in seen:
            raise ValueError("Duplicate recovery attempt")
        seen.add(item)
        total += integer(row["image_bytes"], 1)
    if total > integer(limit, 1):
        raise ValueError("Complete recovery would exceed the cumulative budget")
    return total


def archived_suffix(chunks, entries, *, first, failed):
    """Only validated earlier entries are eligible for in-place reuse."""
    first, failed = integer(first), integer(failed)
    expected = [row for row in chunks if first <= row["index"] < failed]
    if len(entries) != len(expected):
        raise ValueError("Archived validated-prefix count changed")
    for row, entry in zip(expected, entries):
        if key(row, "index") != key(entry, "chunk") or membership(row) != membership(
            entry
        ):
            raise ValueError("Failed or missing reference in archived prefix")
    return True


def global_gate(
    chunks, entries, *, completed_threads, expected_threads, total, projected
):
    """No scientific consumer runs until complete opaque metadata is verified."""
    if (
        integer(completed_threads) != integer(expected_threads, 1)
        or integer(total) != integer(projected)
        or len(entries) != len(chunks)
    ):
        raise ValueError("Complete global recovery provenance is required")
    for row, entry in zip(chunks, entries):
        if key(row, "index") != key(entry, "chunk") or membership(row) != membership(
            entry
        ):
            raise ValueError("Complete global native membership is required")
    if len({key(row, "chunk") for row in entries}) != len(entries):
        raise ValueError("Duplicate final reference identity")
    return True
