# Autonomous collaboration on Mac and Windows

GitHub Issues hold task requirements; the private Project is a dashboard.
`codex/coordination` holds authoritative grants, reservations and transition
history. `PROJECT_PLAN.md` remains the approved vision. `PROGRESS.md` summarizes
integrated work; individual task checkpoints belong on their issues. Local
Codex sessions perform implementation and review; there is no paid API daemon.
Sleeping both computers pauses implementation, even while GitHub checks run.

## One-time setup and activation

1. The repository owner enables the private-repository plan needed for branch
   protection, confirms collaborator write access, and configures protected
   `main` with `ci/gate` and `automation/policy`, required current-base checks,
   resolved conversations, and no routine bypass/force-push/deletion.
2. Create a **private user Project** and its Status options: Proposed, Ready,
   Running, Review, Integrating, Verifying main, Done, Blocked, Recovery required,
   Needs human. Configure its number and a Project read/write credential in the
   trusted automation environment. Repository `GITHUB_TOKEN` cannot manage user
   Projects. The issue history is usable before Project setup succeeds.
3. Each collaborator authenticates their own `gh` and Codex account locally.
   Use the committed environment/bootstrap instructions; keep existing research
   environments and data intact. Never place Codex credentials in GitHub.
4. Start coordination in observation mode. Inspect PR #30 and original Windows
   research workers before registering/adopting them; missing local files are
   not evidence a process stopped.
5. Complete two small nonconflicting tasks, one per host, through fresh review,
   serial integration, merged-main verification and private candidate creation.
   Only then switch the configured rollout mode to active.

Authentication, subscription choices and private Project access may require the
owner. Agents should prepare the precise configuration and report these missing
prerequisites together; they must not silently claim enforcement is active.

## Everyday use

Start or resume Codex with this goal:

> Continue the approved project roadmap using the repository coordination
> protocol. Prioritize outstanding reviews and repairs, then claim eligible
> tasks for this machine. Implement, test, obtain independent agent review, and
> submit for automatic integration. Keep working while eligible tasks remain.
> Escalate only according to the autonomy policy.

The worker reads [its operating prompt](automation/worker.md), registers its
host/capabilities, obtains one confirmed grant, and uses a dedicated task
worktree. A separate fresh session follows [the reviewer prompt](automation/reviewer.md).
Each host defaults to one implementation task plus an independent review slot.
Task-owned subagents can explore or implement disjoint granted files; the task
owner publishes their combined result and remains accountable for scope.

Add ideas in a GitHub issue or ask your agent to create/triage one, for example:
“Add rally-clip exports after playback proxies.” The [planner](automation/planner.md)
checks duplicates and dependencies, freezes a bounded task, and places sufficiently
specified approved work in Ready. Changes to the project vision or major scope
need a consolidated human decision. No arbitrary external comment authorizes work.

The dashboard moves tasks through Proposed → Ready → Running → Review →
Integrating → Verifying main → Done. Blocked, Recovery required and Needs human
preserve incomplete work. A rejected experiment can be Done when its protocol
and report are complete; it does not mean the model is promoted or the product
milestone is achieved.

## Queue helper and ownership

The cross-platform interface is `python scripts/agent_queue.py`. Global options
include `--repo Ken0u/badminton-match-analyzer`, `--payload FILE` for JSON request
fields, `--task NUMBER`, `--epoch EPOCH`, `--host HOST`, and `--session SESSION`. Run `--help` and each
subcommand's help for required request fields. Commands are:

| Command | Purpose |
| --- | --- |
| `doctor` | Check auth, tools, environment, data availability and coordination prerequisites |
| `register` | Declare authenticated worker, host/session and capability/input hashes |
| `next` | Request the highest-priority eligible nonconflicting task |
| `checkpoint` | Preserve branch, evidence and progress; renew ownership |
| `extend-scope` | Obtain extra path/resource reservations before changing scope |
| `submit` | Submit the granted task and exact PR revision for review |
| `review-next` | Reserve an independent review |
| `review-result` | Submit exact-head/base/spec verdict, findings and limitations |
| `release` | Checkpoint and release eligible code work |
| `recover` | Adopt interrupted work only with required preservation/process evidence |
| `status` | Read queue, reservations and blockers |

Requests use a unique request ID and fenced JSON marked `agent-request:v1` on an
issue. Retry a request with the **same ID**. The confirmed grant binds actor,
host/session, ownership epoch, spec hash, base revision, paths and resources.
Never start from a board label or an unconfirmed claim. Revalidate ownership
before resuming, changing shared state, or publishing. A newer ownership epoch
invalidates old submissions.

A three-hour lease renews at checkpoints and before long operations. A stale
lease enters recovery rather than immediately assigning duplicate work.
Before yielding, record the branch/PR, exact revision, tests, remaining work and
artifact references. Review needs a fresh session, frozen spec, PR head and base;
a self-declared second verdict in the implementation session is insufficient.

Code and base changes invalidate review evidence. Three failed repair rounds
escalate once with a clear blocker. Routine work can merge automatically after
CI and independent review. Automation/security policy, credentials/authentication,
destructive migrations, deployment and model promotion require a non-author
human approval. CI passing does not establish badminton accuracy.

## Research, interrupted jobs and private delivery

Pin `BADMINTON_ROOT` and `BADMINTON_DATA_DIR` before importing configuration in
copied launchers. Use disposable test storage, and preserve actual annotations
and original predictions. GitHub experiment reservations complement the real
shared Store's `run_local_job` GPU admission; isolated Stores must not allow
competing work. A Windows CUDA requirement cannot silently fall back to Mac CPU.

Before recovering a GPU/data task, verify original-host PID, creation time,
working directory, command, Store/job state and durable artifacts. A timeout,
closed chat, offline host or absent observation handle does not prove exit.
Unreachable physical resources remain reserved until verified recovery.

Successful main verification creates private SHA-addressed package/container
candidates; running apps are not auto-upgraded. Raw datasets/videos, private
annotations, credentials, caches and external model weights remain excluded.
Failed main verification pauses claims/merges and opens a repair task. Normal
notifications concern human action, integration/release failure, stalled
recovery or completed milestones.

## Retrospective history and Project synchronization

Preview before applying remote backfill:

```sh
python scripts/backfill_project.py --dry-run
python scripts/backfill_project.py --apply --create-project
# Or reuse an already configured Project:
python scripts/backfill_project.py --apply --project-number 1
```

The tool reads **all pages** of merged/open PRs and open/closed issues. It creates
one closed bounded-deliverable issue per merged PR, a committed-report evidence
index, a recovery record for open PR #30, and proposed remaining roadmap tasks.
It creates the five roadmap milestones. Stable hidden markers prevent duplicates
on retry; existing human-edited issues and Project cards remain intact. It does
not rewrite historical reports, infer that a prototype finished its milestone,
or describe rejected research as a shipped model. Missing Project permissions
produce an owner setup instruction while retaining the created issue history.

`scripts/devops/project.py` exposes `sync_project(gh, repo, owner=..., number=...,
apply=False, backlog_path=..., root=..., revision="HEAD", include_history=True)`.
The injectable `gh` transport implements `api`, `pages`, and `graphql`. Reads
occur in dry run; only `apply=True` writes. `sync_board` projects newly added
issue cards (and repairs unset Status after an interruption); ongoing queue status projection is owned by coordination automation,
not retrospective backfill. Neither tool grants ownership.
