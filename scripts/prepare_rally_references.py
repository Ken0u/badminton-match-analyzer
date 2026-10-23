"""Prepare original source-only rally frames using real shared Store admission."""

import argparse
import json
import os
import sys
from pathlib import Path


def main():
    for name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "AGENT_PROJECT_TOKEN",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
    ):
        os.environ.pop(name, None)
    checkout = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--context-sha256", required=True)
    parser.add_argument("--timestamp", type=Path, required=True)
    parser.add_argument(
        "--stage", choices=("overview", "dense", "reuse"), required=True
    )
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        os.environ["BADMINTON_ROOT"] = str(root)
        os.environ["BADMINTON_DATA_DIR"] = str(root / "data/processed")
        os.environ["BADMINTON_WEIGHTS_DIR"] = str(root / "models/weights")
        sys.path.insert(0, str(checkout / "backend"))
        from badminton.rally_source_reference import run_preparation, run_reuse

        if args.stage == "reuse":
            run_reuse(
                root,
                checkout,
                args.output.resolve(),
                args.context.resolve(strict=True),
                args.context_sha256,
                args.timestamp.resolve(strict=True),
            )
        else:
            run_preparation(
                root,
                checkout,
                args.output.resolve(),
                args.context.resolve(strict=True),
                args.context_sha256,
                args.timestamp.resolve(strict=True),
                stage=args.stage,
                selection_path=args.selection,
            )
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        return 1
    print(json.dumps({"status": "completed", "annotation_accuracy_established": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
