"""Run a frozen CPU player/pose probe without touching reviewed annotations."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "data", "weights", "manifest", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    for name, value in (
        ("ROOT", args.root),
        ("DATA_DIR", args.data),
        ("WEIGHTS_DIR", args.weights),
    ):
        os.environ[f"BADMINTON_{name}"] = str(value.resolve())
    code_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(code_root / "backend"))
    from badminton.player_probe import run_probe

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    code_sha = subprocess.check_output(
        ["git", "-C", str(code_root), "rev-parse", "HEAD"], text=True
    ).strip()
    receipt = run_probe(
        args.root, args.data, args.weights, manifest, args.output, code_sha=code_sha
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "job_id": receipt["job_id"],
                "output": str(args.output),
                "variants": receipt["variants"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
