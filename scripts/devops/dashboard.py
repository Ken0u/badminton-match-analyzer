"""Quiet, idempotent issue projection; coordination state remains authoritative."""

import html
from datetime import datetime, timezone

MARKER = "<!-- agent-dashboard:v1 -->"


def cell(value):
    return (
        html.escape(str(value))
        .replace("|", "&#124;")
        .replace("\n", " ")
        .replace("@", "&#64;")
    )


def render(state, mode, now):
    lines = [
        MARKER,
        "## Shared agent dashboard",
        "",
        f"Mode: **{cell(mode)}**. Claims paused: **{bool(state.get('paused'))}**.",
        "",
        "| Task | Status | Owner / host | Lease (UTC) | Blocker / delivery |",
        "| --- | --- | --- | --- | --- |",
    ]
    tasks = sorted(
        state.get("tasks", {}).items(), key=lambda item: int(item[0]), reverse=True
    )
    visible = [item for item in tasks if item[1]["status"] != "done"][:50]
    visible += [item for item in tasks if item[1]["status"] == "done"][:10]
    for key, task in visible:
        claim = task.get("claim", {})
        expiry = claim.get("expires_at")
        lease = (
            datetime.fromtimestamp(expiry, timezone.utc).isoformat() if expiry else "—"
        )
        owner = f"{str(claim.get('actor', '—'))[:64]} / {str(claim.get('host_id', '—'))[:64]}"
        reason = str(
            task.get("delivery_error")
            or task.get("integration_error")
            or task.get("reason", "")
        )[:200]
        lines.append(
            f"| #{key} | {cell(task['status'])} | {cell(owner)} | {lease} | {cell(reason)} |"
        )
    lines += [
        "",
        "### Worker availability",
        "",
        "A current lease indicates ownership, not proof that a host or GPU process is alive.",
        "",
    ]
    if len(visible) < len(tasks):
        lines += [
            "",
            "Older tasks remain available in Issues, the Project and queue status.",
        ]
    for worker in sorted(
        state.get("workers", {}).values(), key=lambda w: (w["host_id"], w["session_id"])
    )[-50:]:
        claims = [
            c
            for task in state.get("tasks", {}).values()
            for c in (task.get("claim"), task.get("review_claim"))
            if c
            and c.get("host_id") == worker["host_id"]
            and c.get("session_id") == worker["session_id"]
            and task["status"] != "done"
        ]
        status = (
            "current lease"
            if any(c.get("expires_at", 0) > now for c in claims)
            else "expired ownership; recovery required"
            if claims
            else "registered; availability unconfirmed"
        )
        lines.append(
            f"- {cell(worker['actor'][:64])} / {cell(worker['host_id'][:64])} / {cell(worker['session_id'][:64])}: {status}"
        )
    lines += ["", "### Recent verified merges", ""]
    done = [
        t
        for t in state.get("tasks", {}).values()
        if t.get("status") == "done" and t.get("merge_sha")
    ]
    for task in sorted(
        done, key=lambda t: t.get("integration", {}).get("at", 0), reverse=True
    )[:10]:
        lines.append(
            f"- `{task.get('verified_by_repair', task['merge_sha'])}`"
            + (" — candidate pending" if task.get("delivery_pending") else "")
        )
    return "\n".join(lines) + "\n"


def publish(gh, state, mode, now):
    issues = gh.pages("issues?state=all&labels=agent-control&per_page=100")
    if len(issues) != 1:
        raise ValueError("Exactly one agent-control issue is required")
    issue = issues[0]
    body = (
        (issue.get("body") or "").split(MARKER, 1)[0].rstrip()
        + "\n\n"
        + render(state, mode, now)
    )
    if body != issue.get("body"):
        gh.repo(f"issues/{issue['number']}", method="PATCH", data={"body": body})
