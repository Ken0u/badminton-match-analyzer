"""Pin original research roots before importing the frozen study consumer."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", required=True, type=Path)
    args, _ = parser.parse_known_args()
    root = args.root.resolve()
    os.environ["BADMINTON_ROOT"] = str(root)
    os.environ["BADMINTON_DATA_DIR"] = str(root / "data/processed")
    for name in tuple(os.environ):
        if name in {
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "AGENT_PROJECT_TOKEN",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
        }:
            os.environ.pop(name, None)
    from badminton.shuttle_selection_study import main as run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
