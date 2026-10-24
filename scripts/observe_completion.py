"""Actions-only trusted completion launch/observation entry point."""

import argparse
import json
import os
from pathlib import Path

from devops.completion_observer import (
    CONTROLLER,
    OBSERVER,
    CompletionGitHub,
    launch,
    observe,
)
from devops.github import GitHubError

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("launch", "observe"))
    args = parser.parse_args(argv)
    config = json.loads((ROOT / ".github/automation.json").read_text(encoding="utf-8"))
    expected = CONTROLLER if args.command == "launch" else OBSERVER
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != config["repository"]
        or os.environ.get("GITHUB_WORKFLOW_REF")
        != f"{config['repository']}/.github/workflows/{expected}@refs/heads/main"
        or (
            args.command == "observe"
            and os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        )
    ):
        parser.error(
            "Completion operations require their trusted main Actions workflow"
        )
    gh = CompletionGitHub(config["repository"], args.command)
    try:
        if args.command == "launch":
            result = launch(gh, config)
        else:
            inputs = {
                key: os.environ.get("OBSERVE_" + key.upper())
                for key in (
                    "task_id",
                    "epoch",
                    "stage",
                    "source_sha",
                    "attempt",
                    "coordination_sha",
                )
            }
            result = observe(gh, config, inputs)
    except (GitHubError, KeyError, TypeError, ValueError, OSError) as exc:
        # Payloads, token values and transport diagnostics are not logged.
        result = {
            "outcome": "unknown",
            "error_type": type(exc).__name__,
            "verification_accepted": False,
        }
    print(json.dumps(result, sort_keys=True))
    return int(result["outcome"] in {"unknown", "timeout_unknown"})


if __name__ == "__main__":
    raise SystemExit(main())
