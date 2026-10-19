"""Inspect a workstation or initialize a disposable linked worktree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from devops.environment import PROFILES, bootstrap, doctor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="review")
    parser.add_argument("--python", choices=("3.10", "3.12"), default="3.12")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--install", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.install:
        try:
            bootstrap(args.profile, root, args.python)
        except (ValueError, OSError) as error:
            parser.exit(1, f"{error}\n")
        return 0
    result = doctor(args.profile, root)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
