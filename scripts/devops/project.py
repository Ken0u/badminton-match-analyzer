"""Idempotent issue history and optional GitHub Project v2 projection.

Only ``sync_project(..., apply=True)`` writes remotely. A GitHub Project is a
projection; queue ownership remains on the coordination branch. No application
configuration, data, research outputs, or credentials are imported here.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_REPO = "Ken0u/badminton-match-analyzer"
MARKER = "badminton-backfill:"
STATUS_OPTIONS = [
    "Proposed",
    "Ready",
    "Running",
    "Review",
    "Integrating",
    "Verifying main",
    "Done",
    "Blocked",
    "Recovery required",
    "Needs human",
]


class GitHub:
    """Small injectable gh transport. JSON travels on stdin, never shell text."""

    def _run(self, args: list[str], payload: Any = None) -> Any:
        command = ["gh", *args]
        if payload is not None:
            command.extend(["--input", "-"])
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"gh failed ({result.returncode}): {result.stderr.strip()}"
            )
        return json.loads(result.stdout) if result.stdout.strip() else None

    def api(self, path: str, *, method: str = "GET", data: Any = None) -> Any:
        return self._run(["api", "--method", method, path], data)

    def pages(self, path: str) -> list[dict[str, Any]]:
        pages = self._run(["api", "--paginate", "--slurp", path])
        return [item for page in pages for item in page]

    def graphql(self, query: str, **variables: Any) -> dict[str, Any]:
        result = self._run(["api", "graphql"], {"query": query, "variables": variables})
        if result.get("errors"):
            raise RuntimeError(
                "GraphQL request failed: " + json.dumps(result["errors"])
            )
        return result["data"]


def marker(key: str) -> str:
    return f"<!-- {MARKER}{key} -->"


def index_issues(issues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed = {}
    for issue in issues:
        if "pull_request" in issue:
            continue
        for key in re.findall(
            r"<!-- badminton-backfill:([^\s]+) -->", issue.get("body") or ""
        ):
            if key in indexed:
                raise ValueError(
                    f"Duplicate backfill marker {key}; reconcile existing issues first"
                )
            indexed[key] = issue
    return indexed


def report_links(root: Path, repo: str, revision: str) -> list[str]:
    # Only committed reports belong in history. Local/untracked research is not evidence.
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", revision, "docs"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", revision],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return [
        f"[{Path(path).name}](https://github.com/{repo}/blob/{revision}/{path})"
        for path in result.stdout.splitlines()
        if path.endswith("_REPORT.md")
    ]


def historical_deliverables(
    pulls: list[dict[str, Any]],
    reports: list[str],
    repo: str,
) -> list[dict[str, Any]]:
    records = []
    for pull in pulls:
        number = pull["number"]
        if pull.get("merged_at"):
            records.append(
                {
                    "key": f"pr:{number}",
                    "title": f"Delivered increment: {pull['title']}",
                    "status": "Done",
                    "state": "closed",
                    "milestone": None,
                    "body": (
                        f"Retrospective record for merged [PR #{number}]({pull['html_url']}).\n\n"
                        f"Merged: {pull['merged_at']}; commit: `{pull.get('merge_commit_sha')}`.\n\n"
                        "Completed here means this PR's bounded deliverable was integrated. "
                        "It does not mark an entire product milestone complete or establish "
                        "automatic annotation accuracy. Experiments may be completed with a "
                        "rejected model; consult their reports for promotion decisions.\n\n"
                        "Original implementation and review history remain on the linked PR."
                    ),
                }
            )
        elif number == 30 and pull.get("state") == "open":
            records.append(
                {
                    "key": "pr:30",
                    "title": f"Existing work: {pull['title']}",
                    "status": "Recovery required",
                    "state": "open",
                    "milestone": None,
                    "body": (
                        f"Existing [PR #30]({pull['html_url']}) must be inventoried on its "
                        "original host before adoption. Do not duplicate its implementation or "
                        "restart research processes. Confirm branch, process creation time, "
                        "Store admission, durable artifacts and exact-head checks.\n\n"
                        "This record is not an executable task or an automatic reassignment."
                    ),
                }
            )
    if reports:
        records.append(
            {
                "key": "report-index:v1",
                "title": "Historical evidence index (not accuracy certification)",
                "status": "Done",
                "state": "closed",
                "milestone": None,
                "body": (
                    "Committed research and capability reports at the backfill source revision. "
                    "This completed inventory includes rejected experiments and prototypes; "
                    "it does not promote models or complete the full-match objective.\n\n"
                    + "\n".join(f"- {link}" for link in reports)
                ),
            }
        )
    return records


def task_body(entry: dict[str, Any]) -> str:
    spec = entry["spec"]
    return (
        f"{spec['outcome']}\n\n"
        "Acceptance criteria:\n"
        + "\n".join(f"- {value}" for value in spec["acceptance"])
        + "\n\nThis issue is a bounded roadmap task. Queue admission requires validation "
        "of the structured specification and explicit Ready status.\n\n"
        "<!-- agent-task:v1 -->\n```json\n"
        + json.dumps(spec, indent=2, sort_keys=True)
        + "\n```"
    )


def sync_project(
    gh: GitHub,
    repo: str = DEFAULT_REPO,
    *,
    owner: str = "Ken0u",
    number: int | None = None,
    apply: bool = False,
    backlog_path: Path,
    root: Path,
    revision: str = "HEAD",
    include_history: bool = True,
) -> dict[str, Any]:
    """Reconcile issue history/backlog and optionally Project v2.

    ``gh`` is an injectable transport implementing api/pages/graphql. Dry runs
    perform reads only and return proposed changes. Keys are permanent hidden
    markers searched across *all* open and closed issues. Existing issue bodies,
    state, and human planning edits are preserved. Project failure is reported
    separately after issues are durable; rerunning safely resumes projection.
    """
    backlog = json.loads(backlog_path.read_text(encoding="utf-8"))
    existing = index_issues(gh.pages(f"repos/{repo}/issues?state=all&per_page=100"))
    milestones = gh.pages(f"repos/{repo}/milestones?state=all&per_page=100")
    by_milestone = {item["title"]: item["number"] for item in milestones}
    changes: list[dict[str, Any]] = []
    for milestone in backlog["milestones"]:
        if milestone["key"] not in by_milestone:
            changes.append({"action": "create-milestone", "title": milestone["key"]})
            if apply:
                created = gh.api(
                    f"repos/{repo}/milestones",
                    method="POST",
                    data={
                        "title": milestone["key"],
                        "description": milestone["description"],
                    },
                )
                by_milestone[milestone["key"]] = created["number"]
    records = []
    if include_history:
        pulls = gh.pages(
            f"repos/{repo}/pulls?state=all&per_page=100&sort=created&direction=asc"
        )
        reports = report_links(root, repo, revision)
        records.extend(historical_deliverables(pulls, reports, repo))
    for entry in backlog["tasks"]:
        records.append(
            {
                "key": "task:" + entry["key"],
                "title": entry["title"],
                "status": entry.get("status", "Proposed"),
                "state": "open",
                "milestone": entry["spec"]["milestone"],
                "body": task_body(entry),
            }
        )
    keys = [item["key"] for item in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate requested backfill keys")
    projected = []
    for record in records:
        issue = existing.get(record["key"])
        if issue is None:
            changes.append(
                {
                    "action": "create-issue",
                    "key": record["key"],
                    "title": record["title"],
                    "state": record["state"],
                }
            )
            if apply:
                payload = {
                    "title": record["title"],
                    "body": marker(record["key"]) + "\n\n" + record["body"],
                }
                if record["milestone"] in by_milestone:
                    payload["milestone"] = by_milestone[record["milestone"]]
                issue = gh.api(f"repos/{repo}/issues", method="POST", data=payload)
        if issue is not None:
            # Closing history is resumable if the preceding create succeeded but
            # the process died before closing it. Never reopen human-closed tasks.
            if record["state"] == "closed" and issue["state"] != "closed":
                changes.append({"action": "close-history", "key": record["key"]})
                if apply:
                    issue = gh.api(
                        f"repos/{repo}/issues/{issue['number']}",
                        method="PATCH",
                        data={"state": "closed", "state_reason": "completed"},
                    )
            projected.append(
                (issue, "Done" if issue["state"] == "closed" else record["status"])
            )
    result: dict[str, Any] = {
        "apply": apply,
        "changes": changes,
        "issues": len(records),
    }
    if number is not None:
        try:
            result["project"] = sync_board(gh, owner, number, projected, apply=apply)
        except RuntimeError as error:
            result["project_warning"] = (
                f"Issue history is preserved. Project sync failed: {error}. "
                f"Owner {owner} must grant the automation credential Project read/write "
                "access, then rerun with --project-number. Do not delete/recreate issues."
            )
    else:
        result["project_warning"] = (
            f"Project not configured. Owner {owner}: create a private user Project, "
            "set its number and a Project read/write credential, then rerun. "
            "Issue history remains reusable."
        )
    return result


def create_private_project(gh: GitHub, owner: str, title: str) -> dict[str, Any]:
    """Create/configure a new private user Project, or reuse one by exact title.

    Existing projects are never reconfigured: replacing single-select options
    can clear their values. The caller must explicitly opt into this mutation.
    """
    cursor = None
    owner_id = None
    matches = []
    while True:
        data = gh.graphql(
            "query($owner:String!,$cursor:String){user(login:$owner){id projectsV2("
            "first:100,after:$cursor){nodes{id number title closed public} "
            "pageInfo{hasNextPage endCursor}}}}",
            owner=owner,
            cursor=cursor,
        )["user"]
        if not data:
            raise RuntimeError("Project owner is inaccessible")
        owner_id = data["id"]
        matches.extend(
            item
            for item in data["projectsV2"]["nodes"]
            if item["title"] == title and not item["closed"]
        )
        page = data["projectsV2"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]
    if len(matches) > 1:
        raise RuntimeError(
            "Multiple matching Projects; pass the explicit Project number"
        )
    if matches:
        if matches[0]["public"]:
            raise RuntimeError("Matching Project is public; owner must make it private")
        return matches[0]
    created = gh.graphql(
        "mutation($owner:ID!,$title:String!){createProjectV2(input:{ownerId:$owner,"
        "title:$title}){projectV2{id number title}}}",
        owner=owner_id,
        title=title,
    )["createProjectV2"]["projectV2"]
    gh.graphql(
        "mutation($id:ID!){updateProjectV2(input:{projectId:$id,public:false})"
        "{projectV2{id}}}",
        id=created["id"],
    )
    # New projects have no cards, so initializing Status options cannot erase
    # existing task values. Existing projects take the non-mutating path above.
    fields = gh.graphql(
        "query($id:ID!){node(id:$id){... on ProjectV2{fields(first:100){nodes{"
        "... on ProjectV2SingleSelectField{id name}}}}}}",
        id=created["id"],
    )["node"]["fields"]["nodes"]
    status = next((field for field in fields if field.get("name") == "Status"), None)
    options = [
        {"name": name, "color": "GRAY", "description": name} for name in STATUS_OPTIONS
    ]
    if status:
        gh.graphql(
            "mutation($id:ID!,$options:[ProjectV2SingleSelectFieldOptionInput!]!){"
            "updateProjectV2Field(input:{fieldId:$id,singleSelectOptions:$options})"
            "{projectV2Field{... on ProjectV2SingleSelectField{id}}}}",
            id=status["id"],
            options=options,
        )
    else:
        gh.graphql(
            "mutation($id:ID!,$options:[ProjectV2SingleSelectFieldOptionInput!]!){"
            "createProjectV2Field(input:{projectId:$id,dataType:SINGLE_SELECT,"
            'name:"Status",singleSelectOptions:$options}){projectV2Field{'
            "... on ProjectV2SingleSelectField{id}}}}",
            id=created["id"],
            options=options,
        )
    return created


def sync_board(
    gh: GitHub,
    owner: str,
    number: int,
    issues: list[tuple[dict[str, Any], str]],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Project projection with paginated reads and no changes in dry-run mode."""
    data = gh.graphql(
        "query($owner:String!,$number:Int!){user(login:$owner){projectV2(number:$number)"
        "{id fields(first:100){nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}}}}",
        owner=owner,
        number=number,
    )
    project = (data.get("user") or {}).get("projectV2")
    if not project:
        raise RuntimeError("user Project not found or inaccessible")
    status = next(
        (
            field
            for field in project["fields"]["nodes"]
            if field.get("name") == "Status"
        ),
        None,
    )
    if not status:
        raise RuntimeError("Project requires a single-select Status field")
    options = {item["name"]: item["id"] for item in status["options"]}
    missing = sorted(set(STATUS_OPTIONS) - options.keys())
    if missing:
        # Do not replace existing status options: GitHub deletes/recreates IDs,
        # which can clear human-managed values. Owner configures this once.
        raise RuntimeError(
            "Add these Status options to the Project: " + ", ".join(missing)
        )
    content = {}
    valued = set()
    cursor = None
    while True:
        result = gh.graphql(
            "query($id:ID!,$cursor:String){node(id:$id){... on ProjectV2{items(first:100,after:$cursor)"
            '{nodes{id content{... on Issue{id}} fieldValueByName(name:"Status"){... on '
            "ProjectV2ItemFieldSingleSelectValue{name}}} pageInfo{hasNextPage endCursor}}}}}",
            id=project["id"],
            cursor=cursor,
        )["node"]["items"]
        for item in result["nodes"]:
            if item.get("content"):
                content[item["content"]["id"]] = item["id"]
                if item.get("fieldValueByName"):
                    valued.add(item["content"]["id"])
        if not result["pageInfo"]["hasNextPage"]:
            break
        cursor = result["pageInfo"]["endCursor"]
    changes = []
    for issue, value in issues:
        issue_id = issue["node_id"]
        item_id = content.get(issue_id)
        if item_id and issue_id in valued:
            # Preserve manually/queue-managed status, repairing only unset values.
            continue
        changes.append({"issue": issue["number"], "status": value})
        if apply:
            if item_id is None:
                item_id = gh.graphql(
                    "mutation($project:ID!,$content:ID!){addProjectV2ItemById(input:"
                    "{projectId:$project,contentId:$content}){item{id}}}",
                    project=project["id"],
                    content=issue_id,
                )["addProjectV2ItemById"]["item"]["id"]
            gh.graphql(
                "mutation($project:ID!,$item:ID!,$field:ID!,$value:String!){"
                "updateProjectV2ItemFieldValue(input:{projectId:$project,itemId:$item,"
                "fieldId:$field,value:{singleSelectOptionId:$value}}){projectV2Item{id}}}",
                project=project["id"],
                item=item_id,
                field=status["id"],
                value=options[value],
            )
    return {"id": project["id"], "add": changes}
