"""Compare explicit native review JSON privately; never inspect images or assessors."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_rally_review import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENTS,
    MAX_MANIFEST_BYTES,
    MAX_PLAN_BYTES,
    MAX_TOTAL_BYTES,
    document_paths,
    ordinary_path,
    read_bytes,
    require,
)


def run(args):
    from badminton.rally_review_comparison import compare_streams
    from badminton.rally_review_contract import strict_json

    plan = read_bytes(args.plan, MAX_PLAN_BYTES)
    total = len(plan)
    documents, manifests, seen = {}, {}, set()
    for lane in ("independent_a", "independent_b", "source_adjudication"):
        name = getattr(args, lane)
        if name is None:
            continue
        path = ordinary_path(name)
        raw = read_bytes(path, MAX_MANIFEST_BYTES)
        total += len(raw)
        require(total <= MAX_TOTAL_BYTES, "Combined JSON inputs exceed the byte limit")
        paths = document_paths(raw, path.parent, strict_json)
        require(
            len(seen) + len(paths) <= MAX_DOCUMENTS,
            "Combined document count exceeds the limit",
        )
        documents[lane] = []
        manifests[lane] = {"sha256": hashlib.sha256(raw).hexdigest(), "documents": []}
        for doc_path in paths:
            normalized = os.path.normcase(str(ordinary_path(doc_path)))
            require(normalized not in seen, "Duplicate document path across streams")
            seen.add(normalized)
            doc = read_bytes(doc_path, MAX_DOCUMENT_BYTES)
            total += len(doc)
            require(
                total <= MAX_TOTAL_BYTES, "Combined JSON inputs exceed the byte limit"
            )
            documents[lane].append(doc)
            manifests[lane]["documents"].append(hashlib.sha256(doc).hexdigest())
    result = compare_streams(plan, **documents, source_id=args.source)
    result["input_manifests"] = manifests
    result["input_bytes"] = total
    encoded = (
        json.dumps(
            result, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
        )
        + "\n"
    ).encode("utf-8")
    require(len(encoded) <= MAX_TOTAL_BYTES, "Comparison output exceeds the byte limit")
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
    parser.add_argument("--independent-a", type=Path, required=True)
    parser.add_argument("--independent-b", type=Path, required=True)
    parser.add_argument("--source-adjudication", type=Path)
    parser.add_argument("--source", help="Explicit source ID when the plan is a bundle")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run(args)
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        parser.exit(
            2, "Review comparison failed; inputs and existing output are preserved.\n"
        )


if __name__ == "__main__":
    main()
