"""Prepare bounded source-only packets through the original shared Store."""

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "AGENT_PROJECT_TOKEN", "OPENAI_API_KEY"):
        os.environ.pop(name, None)
    checkout = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sources",
        type=Path,
        default=checkout / "data/manifests/shuttle_review_sources_v1.json",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=checkout / "data/manifests/shuttle_review_packet_protocol_v1.json",
    )
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        os.environ["BADMINTON_ROOT"] = str(root)
        os.environ["BADMINTON_DATA_DIR"] = str(root / "data" / "processed")
        os.environ["BADMINTON_WEIGHTS_DIR"] = str(root / "models" / "weights")
        sys.path.insert(0, str(checkout / "backend"))
        from badminton.shuttle_sources import run_preparation

        run_preparation(
            root,
            args.output.resolve(),
            sources_path=args.sources.resolve(strict=True),
            protocol_path=args.protocol.resolve(strict=True),
        )
    except Exception as error:
        # Detailed local evidence belongs in the ignored lineage, never console URLs
        # or credentials embedded in downloader/OS exception messages.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        return 1
    print(json.dumps({"status": "completed", "annotation_accuracy_established": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
