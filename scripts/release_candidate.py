"""Validate declared candidate visibility and inventory immutable source builds."""

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


def checked_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Expected an immutable commit SHA")
    return value


def source_sha():
    return checked_sha(os.environ.get("SOURCE_SHA", ""))


def checkout_sha(root):
    return checked_sha(
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
    )


def visibility_policy(gh, config):
    visibility = config.get("candidate_visibility")
    if visibility not in ("private", "public"):
        raise ValueError("Explicit private/public candidate_visibility is required")
    repository = gh.repo()
    if (
        not isinstance(repository.get("private"), bool)
        or str(repository.get("full_name", "")).casefold()
        != config["repository"].casefold()
        or repository["private"] != (visibility == "private")
    ):
        raise ValueError("Candidate visibility must match the configured repository")
    return visibility


def verified_checkout(root, source):
    if checkout_sha(root) != source:
        raise ValueError("Build checkout does not match the verified source")
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=root, check=True)


def validate(gh, source):
    config = json.loads((ROOT / ".github/automation.json").read_text(encoding="utf-8"))
    visibility = visibility_policy(gh, config)
    publisher = checkout_sha(ROOT)
    verified_checkout(ROOT, publisher)
    runs = gh.repo("actions/workflows/ci.yml/runs?per_page=100")["workflow_runs"]
    for revision in dict.fromkeys((source, publisher)):
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", revision, "origin/main"],
            cwd=ROOT,
            check=True,
        )
        valid = [
            r
            for r in runs
            if (r["event"] == "push" and r["head_sha"] == revision)
            or (
                r["event"] == "workflow_dispatch"
                and r.get("display_title") == f"Verify {revision}"
            )
        ]
        latest = max(valid, key=lambda r: r["id"]) if valid else {}
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ValueError(
                "Current merged-main verification of source and publisher must "
                "succeed before publishing"
            )
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"source={source}\n")
            stream.write(f"publisher={publisher}\n")
            stream.write(f"visibility={visibility}\n")
    return {"source": source, "publisher": publisher, "visibility": visibility}


def inventory(source, dist, *, source_root, publisher, visibility):
    allowed = sorted(p for p in dist.iterdir() if p.name.endswith((".whl", ".tar.gz")))
    if (
        len(allowed) != 2
        or not all(
            p.name.startswith("badminton_match_analyzer-")
            and p.is_file()
            and not p.is_symlink()
            for p in allowed
        )
        or sorted(p.name.endswith(".whl") for p in allowed) != [False, True]
    ):
        raise ValueError(
            "Candidate directory must contain exactly this project's wheel and sdist"
        )
    receipt = {
        "source_sha": source,
        "publisher_sha": publisher,
        "visibility": visibility,
        "build_url": f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}",
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in allowed},
        "lock_sha256": hashlib.sha256(
            (source_root / "uv.lock").read_bytes()
        ).hexdigest(),
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


def package_visibility(gh, target, visibility, *, allow_missing=False):
    if target not in ("review", "cpu") or visibility not in ("private", "public"):
        raise ValueError("Invalid candidate image target or visibility")
    name = f"badminton-match-analyzer-{target}"
    try:
        package = gh.api(f"users/Ken0u/packages/container/{name}")
    except GitHubError as exc:
        if not re.search(r"\(HTTP 404\)\s*$", str(exc)):
            raise
        if visibility == "private" and allow_missing:
            # New GHCR packages default private; public mode never assumes visibility.
            return {"name": name, "visibility": "private", "exists": False}
        raise ValueError(
            "Candidate package must exist with the declared visibility; "
            "the owner must configure its package settings"
        ) from exc
    if (
        package.get("visibility") != visibility
        or package.get("name") != name
        or package.get("package_type") != "container"
    ):
        raise ValueError(
            "GHCR package does not match declared visibility; refuse upload"
        )
    return {"name": name, "visibility": visibility, "exists": True}


def image_receipt(
    gh, source, target, digest, *, source_root, publisher, visibility, config
):
    if target not in ("review", "cpu") or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", digest
    ):
        raise ValueError("Invalid image receipt")
    package = package_visibility(gh, target, visibility)
    receipt = {
        "source_sha": source,
        "publisher_sha": publisher,
        "visibility": package["visibility"],
        "image": f"ghcr.io/{config['repository'].lower()}-{target}@{digest}",
        "platform": "linux/amd64",
    }
    dist = source_root / "dist"
    dist.mkdir(exist_ok=True)
    (dist / f"image-{target}.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["validate", "inventory", "package-visibility", "image-receipt"],
    )
    parser.add_argument("--target", choices=["review", "cpu"])
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    config = json.loads((ROOT / ".github/automation.json").read_text(encoding="utf-8"))
    gh = GitHub(config["repository"])
    source = source_sha()
    if args.command == "validate":
        validate(gh, source)
    else:
        visibility = visibility_policy(gh, config)
        publisher = checkout_sha(ROOT)
        if publisher != checked_sha(os.environ.get("PUBLISHER_SHA", "")):
            raise ValueError("Publisher checkout changed after eligibility")
        verified_checkout(ROOT, publisher)
        if args.command == "package-visibility":
            package_visibility(gh, args.target, visibility, allow_missing=True)
        else:
            if args.source_root is None:
                raise ValueError("An explicit immutable build checkout is required")
            source_root = args.source_root.resolve()
            verified_checkout(source_root, source)
            if args.command == "inventory":
                inventory(
                    source,
                    source_root / "dist",
                    source_root=source_root,
                    publisher=publisher,
                    visibility=visibility,
                )
            else:
                image_receipt(
                    gh,
                    source,
                    os.environ.get("IMAGE_TARGET", ""),
                    os.environ.get("IMAGE_DIGEST", ""),
                    source_root=source_root,
                    publisher=publisher,
                    visibility=visibility,
                    config=config,
                )


if __name__ == "__main__":
    main()
