"""Validate explicitly supplied review JSON structure without assessing images.

This offline consumer establishes no source truth, assessor provenance, original
plan acquisition proof or scientific execution authority. Detailed documents are
written only to the explicitly named private output; stdout is aggregate metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath

CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT / "backend"))
sys.dont_write_bytecode = True

MAX_PLAN_BYTES = 16 * 1024**2
MAX_MANIFEST_BYTES = 1024**2
MAX_DOCUMENT_BYTES = 2 * 1024**2
MAX_TOTAL_BYTES = 128 * 1024**2
MAX_DOCUMENTS = 4096
IO_LIMITS = {
    "plan_bytes": MAX_PLAN_BYTES,
    "manifest_bytes": MAX_MANIFEST_BYTES,
    "document_bytes": MAX_DOCUMENT_BYTES,
    "total_input_bytes": MAX_TOTAL_BYTES,
    "documents": MAX_DOCUMENTS,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ordinary_path(value, *, existing=True):
    """Reject symlink/reparse traversal, including an input's parent directories."""
    path = Path(os.path.abspath(value))
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            require(item == path and not existing, "Missing input or directory")
            continue
        require(
            not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            "Symlink or reparse paths are not supported",
        )
        if item != path:
            require(stat.S_ISDIR(info.st_mode), "Input parent must be a directory")
        else:
            require(stat.S_ISREG(info.st_mode), "JSON input must be an ordinary file")
    return path


def file_identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def read_bytes(path, limit):
    path = ordinary_path(path)
    require(path.suffix.lower() == ".json", "Only explicit JSON inputs are supported")
    before = path.lstat()
    require(0 < before.st_size <= limit, "JSON input exceeds its byte limit")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        require(file_identity(before) == file_identity(opened), "JSON input changed")
        raw = stream.read(limit + 1)
        after_open = os.fstat(stream.fileno())
    ordinary_path(path)
    after_path = path.lstat()
    require(
        0 < len(raw) <= limit
        and len(raw) == before.st_size
        and file_identity(before)
        == file_identity(after_open)
        == file_identity(after_path),
        "JSON input changed during its bounded read",
    )
    # Hashing and parsing consume these exact captured bytes, never a second read.
    raw.decode("utf-8")
    return raw


def document_paths(raw, parent, strict_json):
    manifest = strict_json(raw)
    require(
        type(manifest) is dict
        and set(manifest) == {"schema_version", "documents"}
        and type(manifest["schema_version"]) is int
        and manifest["schema_version"] == 1
        and type(manifest["documents"]) is list
        and len(manifest["documents"]) <= MAX_DOCUMENTS,
        "Expected a versioned document-path manifest",
    )
    names = manifest["documents"]
    for name in names:
        require(
            type(name) is str and bool(name), "Relative JSON document path required"
        )
        path = PurePosixPath(name)
        require(
            "\\" not in name
            and not path.is_absolute()
            and str(path) == name
            and all(
                part not in ("", ".", "..") and ":" not in part for part in path.parts
            )
            and path.suffix.lower() == ".json",
            "Unsafe document path",
        )
    require(len(names) == len(set(names)), "Duplicate document paths")
    return [parent / name for name in names]


def run(args):
    from badminton.rally_review_contract import strict_json, validate_stream

    plan = read_bytes(args.plan, MAX_PLAN_BYTES)
    manifest_path = ordinary_path(args.documents)
    manifest = read_bytes(manifest_path, MAX_MANIFEST_BYTES)
    paths = document_paths(manifest, manifest_path.parent, strict_json)
    documents, total = [], len(plan) + len(manifest)
    for path in paths:
        raw = read_bytes(path, MAX_DOCUMENT_BYTES)
        total += len(raw)
        require(total <= MAX_TOTAL_BYTES, "Combined JSON inputs exceed the byte limit")
        documents.append(raw)
    result = validate_stream(plan, documents, args.lane, source_id=args.source)
    encoded = (
        json.dumps(
            result, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
        )
        + "\n"
    ).encode("utf-8")
    require(len(encoded) <= MAX_TOTAL_BYTES, "Validated output exceeds the byte limit")
    output = ordinary_path(args.output, existing=False)
    require(not output.exists(), "Output already exists; preserve the original result")
    with output.open("xb") as stream:
        stream.write(encoded)
    print(
        json.dumps(
            result["summary"], ensure_ascii=False, allow_nan=False, sort_keys=True
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument(
        "--lane",
        choices=("independent_a", "independent_b", "source_adjudication"),
        required=True,
    )
    parser.add_argument(
        "--source", help="Explicit source ID when the plan is a source bundle"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run(args)
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        # Do not echo private document text, local paths or source judgments.
        parser.exit(
            2,
            "Review structure validation failed; inputs and existing output are preserved.\n",
        )


if __name__ == "__main__":
    main()
