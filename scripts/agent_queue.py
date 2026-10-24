"""Cross-platform client and trusted Actions entry point for the agent queue."""

import argparse
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devops.coordinator import (
    HEARTBEAT_MARKER,
    REQUEST_MARKER,
    StateStore,
    integrate,
    reconcile,
    rollout_policy,
)
from devops.github import GitHub, GitHubError

ROOT = Path(__file__).resolve().parents[1]


def load_config():
    return json.loads((ROOT / ".github/automation.json").read_text(encoding="utf-8"))


def doctor(gh, config):
    from devops.environment import doctor as environment_doctor

    result = environment_doctor("review", ROOT)
    result["automation_mode"] = config["mode"]
    manifest = json.loads(
        (ROOT / "backend/badminton/model_manifest.json").read_text(encoding="utf-8")
    )
    result["models"] = {
        key: {
            "name": value["name"],
            "available": (ROOT / "models/weights" / value["name"]).is_file()
            or str(value.get("source", "")).startswith("packaged:"),
        }
        for key, value in manifest.items()
    }
    catalog = ROOT / "data/processed/catalog.sqlite3"
    if catalog.is_file():
        with sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True) as db:
            jobs = [
                json.loads(row[0]) for row in db.execute("SELECT document FROM jobs")
            ]
        result["local_jobs"] = [
            {key: job.get(key) for key in ("id", "kind", "status", "owner_pid")}
            for job in jobs
            if job.get("status") in ("running", "queued")
        ]
    try:
        result["github"] = gh.api("user")["login"]
        result["repository"] = gh.repo()["permissions"]
    except GitHubError as exc:
        result["github_error"] = str(exc)
    try:
        _tip, state = StateStore(gh, config["coordination_branch"]).read()
        result["queue"] = {
            "tasks": len(state["tasks"]),
            "paused": state.get("paused", False),
        }
    except GitHubError as exc:
        result["queue_error"] = str(exc)
    return result


def worker_identity():
    common_git = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=ROOT,
            text=True,
        ).strip()
    )
    # Linked worktrees share the host worker identity without copying ignored data.
    path = common_git.parent / ".cache" / "agent-worker.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = {"host_id": platform.node(), "session_id": uuid4().hex}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value


def save_client_json(path, value):
    """Replace a local receipt only after its complete new bytes are written."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(value, indent=2) + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Preserve the original write failure for a safe diagnostic.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    verbs = (
        "doctor",
        "register",
        "next",
        "checkpoint",
        "extend-scope",
        "submit",
        "review-next",
        "review-result",
        "release",
        "recover",
        "recover-merged",
        "status",
        "plan",
        "reconcile",
        "integrate",
        "heartbeat",
        "pause",
        "resume",
        "human-approved",
    )
    parser.add_argument("command", choices=verbs)
    parser.add_argument(
        "--payload", type=Path, help="JSON request fields; never executed as code"
    )
    parser.add_argument("--task", dest="task_id")
    parser.add_argument("--epoch", type=int)
    parser.add_argument("--host", dest="host_id")
    parser.add_argument("--session", dest="session_id")
    parser.add_argument("--request-id", default=None)
    parser.add_argument(
        "--wait",
        type=int,
        default=30,
        help="Seconds to wait for durable acknowledgement",
    )
    args = parser.parse_args(argv)
    config = load_config()
    gh = GitHub(config["repository"])
    if args.command == "doctor":
        print(json.dumps(doctor(gh, config), indent=2))
        return
    if args.command in ("reconcile", "integrate"):
        if os.environ.get("GITHUB_ACTIONS") != "true":
            parser.error(
                "Privileged commands run only in the trusted Actions controller"
            )
        if os.environ.get("GITHUB_REPOSITORY") != config["repository"]:
            parser.error("Unexpected controller repository")
        if args.command == "integrate":
            rollout_policy(gh, config)
        state = reconcile(gh, config)
        if args.command == "integrate":
            state = integrate(gh, config, state)
            from devops.dashboard import publish

            publish(gh, state, config["mode"], int(time.time()))
        print(
            json.dumps(
                {
                    "mode": config["mode"],
                    "tasks": len(state["tasks"]),
                    "paused": state.get("paused", False),
                }
            )
        )
        return
    _tip, state = StateStore(gh, config["coordination_branch"]).read()
    if args.command == "status":
        value = state
        if args.task_id:
            value = state["tasks"].get(args.task_id, {"status": "unknown-task"})
        elif args.request_id:
            value = state["receipts"].get(args.request_id, {"status": "pending"})
        print(json.dumps(value, indent=2))
        return
    payload = (
        json.loads(args.payload.read_text(encoding="utf-8")) if args.payload else {}
    )
    identity = worker_identity()
    request = {
        **identity,
        **payload,
        "verb": args.command,
        "request_id": args.request_id or uuid4().hex,
    }
    for name in ("task_id", "epoch", "host_id", "session_id"):
        if getattr(args, name) is not None:
            request[name] = getattr(args, name)
    if args.command == "register":
        request.setdefault(
            "capabilities",
            ["cpu", platform.system().lower(), platform.machine().lower()],
        )
        request.setdefault("artifacts", {})
    if args.command == "next":
        request.setdefault(
            "baseline_sha", gh.repo("git/ref/heads/main")["object"]["sha"]
        )
    if args.command == "submit":
        request.setdefault(
            "head_sha",
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
        )
        request.setdefault("base_sha", gh.repo("git/ref/heads/main")["object"]["sha"])
    queue_issues = gh.pages("issues?state=all&labels=agent-control&per_page=100")
    if len(queue_issues) != 1:
        parser.error(
            "Run scripts/setup_automation.py --apply first: one agent-control issue is required"
        )
    request.pop("actor", None)
    body = (
        (HEARTBEAT_MARKER if args.command == "heartbeat" else REQUEST_MARKER)
        + "\n```json\n"
        + json.dumps(request, sort_keys=True, indent=2)
        + "\n```"
    )
    receipt_dir = ROOT / ".cache"
    try:
        receipt_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(
            "Cannot prepare local request receipt directory "
            f"({type(exc).__name__}); request was not submitted."
        ) from None
    heartbeat_path = receipt_dir / "agent-heartbeat-comments.json"
    heartbeats = (
        json.loads(heartbeat_path.read_text(encoding="utf-8"))
        if heartbeat_path.exists()
        else {}
    )
    heartbeat_key = f"{request['host_id']}/{request['session_id']}/{request.get('task_id')}/{request.get('lane', 'implementation')}"
    if args.command == "heartbeat" and heartbeat_key in heartbeats:
        comment = gh.repo(
            f"issues/comments/{heartbeats[heartbeat_key]}",
            method="PATCH",
            data={"body": body},
        )
    else:
        comment = gh.repo(
            f"issues/{queue_issues[0]['number']}/comments",
            method="POST",
            data={"body": body},
        )
    try:
        if args.command == "heartbeat" and heartbeat_key not in heartbeats:
            heartbeats[heartbeat_key] = comment["id"]
            save_client_json(heartbeat_path, heartbeats)
        save_client_json(
            receipt_dir / "agent-last-request.json",
            {"request": request, "comment": comment["html_url"]},
        )
    except OSError as exc:
        raise ValueError(
            json.dumps(
                {
                    "status": "local_receipt_write_failed",
                    "request_id": request["request_id"],
                    "comment": comment["html_url"],
                    "error_type": type(exc).__name__,
                    "instruction": (
                        "Remote request was submitted. Poll status using this ID; "
                        "retry only with the same request ID and payload."
                    ),
                }
            )
        ) from None
    deadline = time.monotonic() + min(60, max(0, args.wait))
    while True:
        _tip, state = StateStore(gh, config["coordination_branch"]).read()
        receipt = state.get("receipts", {}).get(request["request_id"])
        if receipt is not None:
            if receipt.get("actor") != comment["user"]["login"]:
                raise ValueError(
                    "Request ID belongs to a different actor; do not use this grant"
                )
            result = dict(receipt)
            if receipt.get("task_id"):
                result["task"] = state["tasks"][receipt["task_id"]]
            print(json.dumps(result, indent=2))
            return
        if time.monotonic() >= deadline:
            print(
                json.dumps(
                    {
                        "status": "pending",
                        "request_id": request["request_id"],
                        "comment": comment["html_url"],
                        "instruction": "Poll status; do not begin work before a grant.",
                    },
                    indent=2,
                )
            )
            return
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except (GitHubError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
