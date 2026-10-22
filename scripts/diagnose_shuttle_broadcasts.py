"""Prepare, capture and interpret the fixed broadcast shuttle diagnostic."""

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv=None):
    for key in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "AGENT_PROJECT_TOKEN",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
    ):
        os.environ.pop(key, None)
    checkout = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "interpret"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=checkout / "data/manifests/shuttle_broadcast_baseline_protocol_v1.json",
    )
    parser.add_argument("--packet-root", type=Path)
    parser.add_argument("--assessments", type=Path)
    parser.add_argument("--context-sha256")
    parser.add_argument("--resume-receipt", type=Path)
    parser.add_argument("--resume-sha256")
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--terminal-sha256")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    os.environ["BADMINTON_ROOT"] = str(root)
    os.environ["BADMINTON_DATA_DIR"] = str(root / "data/processed")
    os.environ["BADMINTON_WEIGHTS_DIR"] = str(root / "models/weights")
    sys.path.insert(0, str(checkout / "backend"))
    try:
        from badminton.shuttle_broadcast_baseline import interpret, prepare, run

        if args.command == "prepare":
            if args.packet_root is None or args.assessments is None:
                parser.error("prepare requires --packet-root and --assessments")
            result = prepare(
                root,
                args.packet_root,
                args.assessments,
                args.output,
                args.protocol,
            )
        elif args.command == "run":
            if args.context_sha256 is None:
                parser.error("run requires --context-sha256")
            result = run(
                root,
                args.output,
                args.context_sha256,
                protocol_path=args.protocol,
                resume_receipt=args.resume_receipt,
                resume_sha256=args.resume_sha256,
            )
        else:
            if any(
                value is None
                for value in (
                    args.context_sha256,
                    args.terminal,
                    args.terminal_sha256,
                    args.destination,
                )
            ):
                parser.error(
                    "interpret requires context, terminal, hash and destination"
                )
            result = interpret(
                root,
                args.output,
                args.context_sha256,
                args.terminal,
                args.terminal_sha256,
                args.destination,
                protocol_path=args.protocol,
            )
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except Exception as exc:
        # Keep private source locations, process commands and signed URLs private.
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
