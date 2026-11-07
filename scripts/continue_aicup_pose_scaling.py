"""Run the separately granted, memory-bounded private pose continuation.

The outer launcher pins the original workspace before importing application
configuration and removes credentials from the numerical child environment.
Authenticated observations are separate metadata-only parent commands.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def workspace(argv):
    if "--workspace" in argv:
        return Path(argv[argv.index("--workspace") + 1]).resolve()
    if "--prospective" in argv:
        path = Path(argv[argv.index("--prospective") + 1])
        return Path(json.loads(path.read_bytes())["workspace"]).resolve()
    if "--help" in argv or "-h" in argv:
        return Path(__file__).resolve().parents[1]
    raise ValueError("An explicit original workspace or prospective freeze is required")


def private_write(root, path, value):
    path = Path(os.path.abspath(path))
    cache = root / ".cache/pose402-observations"
    if not path.is_relative_to(cache) or path.resolve() != path:
        raise ValueError(
            "Observation output must stay inside the original private cache"
        )
    # Preserve prior observations with atomic replacement; never modify a run.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def observe(argv, quiet=False):
    from datetime import datetime

    parser = argparse.ArgumentParser(
        description="Authenticated metadata observation; no science"
    )
    parser.add_argument("command", choices=("observe-grant", "observe-publication"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publication-url")
    args = parser.parse_args(argv)
    root = args.workspace.resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from devops.coordinator import StateStore, json_block
    from devops.github import GitHub

    gh = GitHub("Ken0u/badminton-match-analyzer")
    if args.command == "observe-grant":
        tip, state = StateStore(gh, "codex/coordination").read()
        task = state["tasks"]["402"]
        claim = task["claim"]
        receipts = [
            receipt
            for receipt in state["receipts"].values()
            if receipt.get("task_id") == "402"
            and receipt.get("status") == "granted"
            and receipt.get("epoch") == claim["epoch"]
            and receipt.get("claim", {}).get("granted_at") == claim["granted_at"]
        ]
        if len(receipts) != 1:
            raise ValueError(
                "Exactly one committed matching scientific grant is required"
            )
        value = {
            "at": time.time(),
            "coordination_sha": tip,
            "task": task,
            "grant_receipt": receipts[0],
            "code_task": state["tasks"]["401"],
        }
    else:
        prefix = (
            "https://github.com/Ken0u/badminton-match-analyzer/issues/402#issuecomment-"
        )
        url = args.publication_url or ""
        if not url.startswith(prefix) or not url[len(prefix) :].isdigit():
            raise ValueError(
                "Publication must be a comment on the owning scientific issue"
            )
        comment = gh.repo("issues/comments/" + url[len(prefix) :])
        value = {
            "author": comment["user"]["login"],
            "url": comment["html_url"],
            "published_at": datetime.fromisoformat(
                comment["created_at"].replace("Z", "+00:00")
            ).timestamp(),
            "intent": json_block(
                comment["body"], "<!-- pose-continuation-intent:v1 -->"
            ),
        }
    private_write(root, args.output, value)
    if not quiet:
        print(json.dumps({"observed": args.command, "new_decodes": 0, "real_fits": 0}))


def refresh_before_worker(argv, root):
    """Only the authenticated parent refreshes evidence; children get no credentials."""

    def option(name):
        flag = "--" + name
        if argv.count(flag) != 1 or argv.index(flag) + 1 >= len(argv):
            raise ValueError("Exactly one " + flag + " is required")
        return argv[argv.index(flag) + 1]

    observe(
        ["observe-grant", "--workspace", str(root), "--output", option("grant-state")],
        quiet=True,
    )
    if argv[0] == "run":
        publication = Path(option("publication"))
        url = json.loads(publication.read_bytes())["url"]
        observe(
            [
                "observe-publication",
                "--workspace",
                str(root),
                "--output",
                str(publication),
                "--publication-url",
                url,
            ],
            quiet=True,
        )


def launch(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("observe-grant", "observe-publication"):
        return observe(argv)
    worker = bool(argv and argv[0] == "--worker")
    if worker:
        argv.pop(0)
    root = workspace(argv)
    if (
        not worker
        and argv
        and argv[0] in ("freeze", "run")
        and not any(flag in argv for flag in ("--help", "-h"))
    ):
        refresh_before_worker(argv, root)
    denied = ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL", "AUTH", "COOKIE")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(word in key.upper() for word in denied)
        and key.upper() not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")
    }
    environment.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    if not worker:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).resolve()),
                "--worker",
                *argv,
            ],
            env=environment,
            check=False,
        )
        if completed.returncode:
            raise SystemExit(completed.returncode)
        return
    if any(any(word in key.upper() for word in denied) for key in os.environ):
        raise ValueError("Scientific worker must not inherit credentials")
    os.environ.update(
        {
            key: value
            for key, value in environment.items()
            if key.startswith("BADMINTON_")
        }
    )
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from badminton.aicup_pose_continuation import main

    main(argv)


if __name__ == "__main__":
    launch()
