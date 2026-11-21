"""Publish the project-trained models and their model card to Hugging Face.

Needs `pip install huggingface_hub` and a prior `hf auth login`. Uploads
exactly the files in project_models.json after checking each one's SHA-256,
so a changed local file is never published under a pinned name.
"""

import argparse
import hashlib
import json
from pathlib import Path

from badminton.config import WEIGHTS

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "scripts/project_models.json"
CARD = ROOT / "docs/MODEL_CARD.md"
FRONT_MATTER = """---
license: cc-by-nc-sa-4.0
library_name: pytorch
pipeline_tag: video-classification
tags:
- badminton
- sports-analytics
- pose-estimation
- re-identification
---

"""


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip", nargs="*", default=[], help="paths to leave out")
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    from huggingface_hub import HfApi

    spec = json.loads(INDEX.read_text(encoding="utf-8"))
    files = [entry for entry in spec["models"] if entry["path"] not in args.skip]
    for entry in files:
        path = WEIGHTS / entry["path"]
        if not path.is_file() or _sha(path) != entry["sha256"]:
            raise SystemExit(f"{path} is missing or does not match its pinned hash")
    api = HfApi()
    repo = spec["repository"]
    api.create_repo(repo, repo_type="model", private=args.private, exist_ok=True)
    for entry in files:
        api.upload_file(
            path_or_fileobj=str(WEIGHTS / entry["path"]),
            path_in_repo=entry["path"],
            repo_id=repo,
            commit_message=f"Add {entry['path']}",
        )
        print(f"Uploaded {entry['path']}")
    api.upload_file(
        path_or_fileobj=(FRONT_MATTER + CARD.read_text(encoding="utf-8")).encode(),
        path_in_repo="README.md",
        repo_id=repo,
        commit_message="Update model card",
    )
    print(f"https://huggingface.co/{repo}")


if __name__ == "__main__":
    main()
