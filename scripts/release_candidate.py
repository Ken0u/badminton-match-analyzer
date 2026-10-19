"""Validate and inventory private candidates without uploading arbitrary files."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devops.github import GitHub, GitHubError

ROOT = Path(__file__).resolve().parents[1]


def source_sha():
    value = os.environ.get("SOURCE_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("SOURCE_SHA must identify an immutable commit")
    return value


def validate(gh, source):
    if not gh.repo()["private"]:
        raise ValueError("Private candidate publishing requires a private repository")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", source, "origin/main"], check=True
    )
    runs = gh.repo("actions/workflows/ci.yml/runs?per_page=100")["workflow_runs"]
    valid = [
        r
        for r in runs
        if (r["event"] == "push" and r["head_sha"] == source)
        or (
            r["event"] == "workflow_dispatch"
            and r.get("display_title") == f"Verify {source}"
        )
    ]
    if not valid or max(valid, key=lambda r: r["id"]).get("conclusion") != "success":
        raise ValueError(
            "Current merged-main verification must succeed before publishing"
        )
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"source={source}\n")


def inventory(source, dist):
    allowed = sorted(p for p in dist.iterdir() if p.name.endswith((".whl", ".tar.gz")))
    if len(allowed) != 2 or not all(
        p.name.startswith("badminton_match_analyzer-") for p in allowed
    ):
        raise ValueError(
            "Candidate directory must contain exactly this project's wheel and sdist"
        )
    receipt = {
        "source_sha": source,
        "build_url": f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}",
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in allowed},
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "dependencies": json.loads(
            subprocess.check_output(
                [
                    sys.executable,
                    "-c",
                    "import importlib.metadata as m,json;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))",
                ],
                text=True,
            )
        ),
        "annotation_accuracy": "not established by software checks",
        "deployment": "not performed",
    }
    (dist / "candidate.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def package_privacy(gh, target):
    name = f"badminton-match-analyzer-{target}"
    try:
        package = gh.api(f"users/Ken0u/packages/container/{name}")
    except GitHubError as exc:
        if "404" not in str(exc):
            raise
        # GitHub creates new GHCR packages private by default; no visibility mutation.
        return
    if package["visibility"] != "private":
        raise ValueError("Existing GHCR package is not private; refuse upload")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["validate", "inventory", "package-privacy", "image-receipt"]
    )
    parser.add_argument("--target", choices=["review", "cpu"])
    args = parser.parse_args()
    config = json.loads((ROOT / ".github/automation.json").read_text(encoding="utf-8"))
    gh = GitHub(config["repository"])
    source = source_sha()
    dist = ROOT / "dist"
    if args.command == "validate":
        validate(gh, source)
    elif args.command == "package-privacy":
        package_privacy(gh, args.target)
    elif args.command == "inventory":
        inventory(source, dist)
    else:
        digest, target = (
            os.environ.get("IMAGE_DIGEST", ""),
            os.environ.get("IMAGE_TARGET", ""),
        )
        if target not in ("review", "cpu") or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", digest
        ):
            raise ValueError("Invalid image receipt")
        dist.mkdir(exist_ok=True)
        (dist / f"image-{target}.json").write_text(
            json.dumps(
                {
                    "source_sha": source,
                    "image": f"ghcr.io/{config['repository'].lower()}-{target}@{digest}",
                    "platform": "linux/amd64",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
