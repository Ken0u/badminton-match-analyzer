"""Project-only projection of authoritative coordination state."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from urllib.parse import quote

from devops.project import DEFAULT_REPO, GitHub, sync_board

STATUSES = {
    "proposed": "Proposed",
    "ready": "Ready",
    "running": "Running",
    "review": "Review",
    "integrating": "Integrating",
    "verifying_main": "Verifying main",
    "done": "Done",
    "blocked": "Blocked",
    "recovery_required": "Recovery required",
    "needs_human": "Needs human",
}


def sync_status(
    gh: GitHub,
    *,
    repo: str,
    owner: str,
    number: int,
    branch: str = "codex/coordination",
) -> dict:
    """Read remote state and project only its managed task issues.

    Historical/backfilled cards absent from state are never changed. The
    coordination branch is read-only; this function only mutates Project cards.
    """
    if type(number) is not int or number <= 0:
        raise ValueError("Project number must be a positive integer")
    payload = gh.api(f"repos/{repo}/contents/state.json?ref={quote(branch, safe='')}")
    if payload.get("encoding") != "base64":
        raise ValueError("Coordination state must have base64 contents")
    try:
        state = json.loads(
            base64.b64decode("".join(payload["content"].split()), validate=True)
        )
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError("Invalid coordination state contents") from error
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or not isinstance(state.get("tasks"), dict)
    ):
        raise ValueError("Unsupported coordination state schema")
    projected = []
    # Validate every task before allowing any Project writes.
    for task_id, task in state["tasks"].items():
        if (
            not isinstance(task_id, str)
            or not task_id.isascii()
            or not task_id.isdigit()
            or int(task_id) <= 0
        ):
            raise ValueError("Coordination task IDs must be positive issue numbers")
        if not isinstance(task, dict) or task.get("status") not in STATUSES:
            raise ValueError(f"Unknown coordination status for task {task_id}")
        issue = gh.api(f"repos/{repo}/issues/{task_id}")
        if (
            "pull_request" in issue
            or issue.get("number") != int(task_id)
            or not issue.get("node_id")
        ):
            raise ValueError(f"Task {task_id} is not a valid repository issue")
        projected.append((issue, STATUSES[task["status"]]))
    return sync_board(gh, owner, number, projected, apply=True, preserve_existing=False)


def main(argv: list[str] | None = None) -> None:
    config_path = Path(__file__).resolve().parents[1] / ".github/automation.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=config.get("repository", DEFAULT_REPO))
    parser.add_argument(
        "--owner", default=config.get("project", {}).get("owner", "Ken0u")
    )
    parser.add_argument(
        "--project-number",
        type=int,
        default=os.environ.get("BADMINTON_PROJECT_NUMBER")
        or config.get("project", {}).get("number"),
    )
    parser.add_argument(
        "--branch", default=config.get("coordination_branch", "codex/coordination")
    )
    args = parser.parse_args(argv)
    if args.project_number is None:
        print(
            json.dumps(
                {
                    "status": "not-configured",
                    "detail": "Project projection skipped: set BADMINTON_PROJECT_NUMBER after owner setup.",
                }
            )
        )
        return
    token = os.environ.get("AGENT_PROJECT_TOKEN", "").strip()
    if not token:
        parser.exit(
            1,
            "Project is configured but AGENT_PROJECT_TOKEN is missing; owner must provide Project read/write access.\n",
        )
    # gh uses this credential only in the trusted projection process; never print it.
    os.environ["GH_TOKEN"] = token
    try:
        result = sync_status(
            GitHub(),
            repo=args.repo,
            owner=args.owner,
            number=args.project_number,
            branch=args.branch,
        )
    except (RuntimeError, ValueError) as error:
        parser.exit(1, f"Project projection failed: {error}\n")
    print(json.dumps({"status": "projected", "project": result}, indent=2))


if __name__ == "__main__":
    main()
