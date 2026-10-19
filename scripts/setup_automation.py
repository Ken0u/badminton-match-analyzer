"""Owner bootstrap for queue controls; default is a read-only configuration preview."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devops.github import GitHub

ROOT = Path(__file__).resolve().parents[1]
PROTECTION = {
    "required_status_checks": {
        "strict": True,
        "contexts": ["ci/gate", "automation/policy"],
    },
    "enforce_admins": True,
    "required_pull_request_reviews": {
        "dismiss_stale_reviews": True,
        "require_code_owner_reviews": False,
        "required_approving_review_count": 0,
    },
    "restrictions": None,
    "required_conversation_resolution": True,
    "allow_force_pushes": False,
    "allow_deletions": False,
}


def setup(gh, *, apply=False, protections=False, enforcement="controller"):
    if enforcement not in ("controller", "github"):
        raise ValueError("Unknown integration enforcement")
    repo = gh.repo()
    if not repo["private"]:
        raise ValueError("This workflow is configured for a private repository")
    issues = gh.pages("issues?state=all&labels=agent-control&per_page=100")
    if len(issues) > 1:
        raise ValueError("Duplicate agent-control issues; reconcile manually")
    result = {
        "repository": repo["full_name"],
        "mode": "observation",
        "control_issue": issues[0]["number"] if issues else None,
        "integration_enforcement": enforcement,
        "subscription_required": False
        if enforcement == "controller"
        else "eligible GitHub plan",
        "protection": PROTECTION if protections or enforcement == "github" else None,
        "owner_action_required": bool(protections or enforcement == "github")
        and not repo["permissions"].get("admin"),
        "enforcement_limit": "Controller checks cannot prevent direct writes or manual merges outside the protocol"
        if enforcement == "controller"
        else "GitHub branch protections required",
    }
    if not apply:
        return result
    if not issues:
        labels = gh.pages("labels?per_page=100")
        if "agent-control" not in {label["name"] for label in labels}:
            gh.repo(
                "labels",
                method="POST",
                data={
                    "name": "agent-control",
                    "color": "5319e7",
                    "description": "Durable local-agent commands and grants",
                },
            )
        issue = gh.repo(
            "issues",
            method="POST",
            data={
                "title": "Agent coordination requests and worker status",
                "labels": ["agent-control"],
                "body": "Durable automation commands live here. See docs/COLLABORATION.md. Observation mode does not grant execution. Never paste credentials or private datasets.",
            },
        )
        result["control_issue"] = issue["number"]
    if protections:
        if not repo["permissions"].get("admin"):
            raise ValueError(
                "Optional branch protections require owner/admin access and an eligible GitHub plan"
            )
        gh.repo("branches/main/protection", method="PUT", data=PROTECTION)
        result["protection_applied"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--protections",
        action="store_true",
        help="Optional server protections; owner/eligible plan only; requires --apply",
    )
    args = parser.parse_args()
    config = json.loads((ROOT / ".github/automation.json").read_text(encoding="utf-8"))
    if args.protections and not args.apply:
        parser.error("--protections requires --apply")
    print(
        json.dumps(
            setup(
                GitHub(config["repository"]),
                apply=args.apply,
                protections=args.protections,
                enforcement=config.get("integration_enforcement", "controller"),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
