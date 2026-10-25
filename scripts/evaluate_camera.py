"""Score explicit raw camera scan/review JSON; no media or model access."""

import argparse
import hashlib
import json
from pathlib import Path

from validate_rally_review import ordinary_path, read_bytes, require

MAX_FILE_BYTES = 16 * 1024**2
MAX_TOTAL_BYTES = 64 * 1024**2


def run(args):
    from badminton.camera_evaluation import evaluate_camera
    from badminton.rally_review_contract import strict_json

    captured = {
        name: read_bytes(getattr(args, name), MAX_FILE_BYTES)
        for name in ("video", "timestamps", "run", "reference")
    }
    require(
        sum(map(len, captured.values())) <= MAX_TOTAL_BYTES, "Input byte limit exceeded"
    )
    parsed = {name: strict_json(raw) for name, raw in captured.items()}
    result = evaluate_camera(
        parsed["video"],
        parsed["timestamps"],
        parsed["run"],
        parsed["reference"],
        tolerance_s=args.tolerance_s,
    )
    result["input_sha256"] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in captured.items()
    }
    encoded = (
        json.dumps(result, allow_nan=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    require(len(encoded) <= MAX_TOTAL_BYTES, "Output byte limit exceeded")
    output = ordinary_path(args.output, existing=False)
    require(not output.exists(), "Output already exists; preserve the original result")
    with output.open("xb") as stream:
        stream.write(encoded)
    print(json.dumps(result["summary"], allow_nan=False, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("video", "timestamps", "run", "reference", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--tolerance-s", type=float, default=0.12)
    args = parser.parse_args(argv)
    try:
        run(args)
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError):
        parser.exit(
            2,
            "Camera evaluation failed; verify source identity, raw scan and native review JSON. Existing files are preserved.\n",
        )


if __name__ == "__main__":
    main()
