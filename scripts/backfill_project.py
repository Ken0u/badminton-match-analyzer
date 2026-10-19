"""Backfill GitHub history/backlog. Defaults to read-only preview."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from devops.project import DEFAULT_REPO, GitHub, create_private_project, sync_project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--owner", default="Ken0u")
    parser.add_argument(
        "--project-number", type=int, default=os.environ.get("BADMINTON_PROJECT_NUMBER")
    )
    parser.add_argument(
        "--create-project",
        action="store_true",
        help="create/reuse the private user Project (requires --apply)",
    )
    parser.add_argument("--project-title", default="Badminton autonomous development")
    parser.add_argument("--backlog", type=Path)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--skip-history", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read-only (default)")
    mode.add_argument(
        "--apply", action="store_true", help="create missing issues/milestones/cards"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.create_project and not args.apply:
        parser.exit(
            1, "--create-project requires --apply; preview issue changes without it.\n"
        )
    try:
        gh = GitHub()
        project_warning = None
        if args.create_project and args.project_number is None:
            try:
                args.project_number = create_private_project(
                    gh,
                    args.owner,
                    args.project_title,
                )["number"]
            except RuntimeError as error:
                project_warning = f"Owner Project setup required: {error}"
        result = sync_project(
            gh,
            args.repo,
            owner=args.owner,
            number=args.project_number,
            apply=args.apply,
            backlog_path=args.backlog or root / ".github/automation/backlog.json",
            root=root,
            revision=args.revision,
            include_history=not args.skip_history,
        )
    except (RuntimeError, ValueError) as error:
        parser.exit(1, f"Backfill failed: {error}\n")
    if project_warning:
        result["project_warning"] = (
            project_warning + "; issue history remains preserved."
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
