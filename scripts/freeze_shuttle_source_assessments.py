"""Credential-free source-only identity validation and exclusive freezing CLI."""

from __future__ import annotations

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
    root = Path(__file__).resolve().parents[1]
    os.environ["BADMINTON_ROOT"] = str(root)
    os.environ["BADMINTON_DATA_DIR"] = str(
        root / ".cache/shuttle-assessment-cli-isolated"
    )
    sys.path.insert(0, str(root / "backend"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "freeze", "verify-freeze"))
    parser.add_argument("--packet-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument(
        "--assessor-a", type=Path, help="V1 original or V2 stream a index"
    )
    parser.add_argument(
        "--assessor-b", type=Path, help="V1 original or V2 stream b index"
    )
    parser.add_argument(
        "--adjudication", type=Path, help="V1 original or V2 adjudication index"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        from badminton.shuttle_source_assessments import (
            encoded,
            freeze,
            load_inputs,
            verify_freeze,
        )

        if args.command == "verify-freeze":
            if args.output is None:
                raise ValueError("Missing output")
            result = verify_freeze(args.output, args.packet_root, args.protocol_sha256)
        elif args.command == "verify":
            if args.protocol is None:
                raise ValueError("Missing protocol")
            inputs = load_inputs(args.packet_root, args.protocol, args.protocol_sha256)
            if args.inputs is not None and args.inputs.read_bytes() != encoded(inputs):
                raise ValueError("Blind input receipt changed")
            # No per-case/session identities are printed by this CLI.
            result = {
                k: inputs[k]
                for k in (
                    "case_count",
                    "requested_context_memberships",
                    "unique_images",
                    "protocol_sha256",
                    "eligibility",
                )
            }
        else:
            if any(
                v is None
                for v in (
                    args.protocol,
                    args.inputs,
                    args.assessor_a,
                    args.assessor_b,
                    args.adjudication,
                    args.output,
                )
            ):
                raise ValueError("Missing freeze arguments")
            result = freeze(
                args.packet_root,
                args.protocol,
                args.protocol_sha256,
                args.inputs,
                args.assessor_a,
                args.assessor_b,
                args.adjudication,
                args.output,
            )
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except Exception as exc:
        # Never print untrusted paths, labels, URLs, session IDs or exception text.
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
