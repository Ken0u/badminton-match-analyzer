# Autonomous collaboration on Mac and Windows

GitHub Issues hold task requirements; the private Project is a dashboard.
`codex/coordination` holds authoritative grants, reservations and transition
history. `PROJECT_PLAN.md` remains the approved vision. `PROGRESS.md` summarizes
integrated work; individual task checkpoints belong on their issues. Local
Codex sessions perform implementation and review; there is no paid API daemon.
Sleeping both computers pauses implementation, even while GitHub checks run.

## One-time setup and activation

1. After this bootstrap PR is merged, the repository owner runs
   `python scripts/setup_automation.py --apply` and confirms collaborator write
   access. Keep `integration_enforcement` set to `controller`: the default works
   on a private GitHub Free repository and requires no GitHub Pro subscription.
   Follow [the owner checklist](OWNER_SETUP.md) for the remaining setup.
2. Create a **private user Project** and its Status options: Proposed, Ready,
   Running, Review, Integrating, Verifying main, Done, Blocked, Recovery required,
   Needs human. Configure its number and a Project read/write credential in the
   trusted automation: repository variable `AGENT_PROJECT_NUMBER` and secret
   `AGENT_PROJECT_TOKEN` (Project read/write and private repository read access).
   Repository `GITHUB_TOKEN` cannot manage user
   Projects. Run `python scripts/backfill_project.py --apply --create-project
   --revision cc1a37b` to create/reuse the board and existing issue history.
   Preserve that historical baseline on retries. The issue history is usable
   before Project setup succeeds.
3. Each collaborator authenticates their own `gh` and Codex account locally.
   Use the committed environment/bootstrap instructions; keep existing research
   environments and data intact. Never place Codex credentials in GitHub.
   Install the pinned uv tool (`python -m pip install uv==0.9.4`) in your tooling
   environment and use its activated PATH. Run `python scripts/bootstrap.py
   --profile review --install` only inside a new linked task worktree. Use
   `--profile cuda` on a compatible Windows/Linux host, or `cpu` for CPU models.
   The Codex CLI is optional for existing desktop sessions.
4. Start coordination in observation mode. Inspect PR #30 and original Windows
   research workers before registering/adopting them; missing local files are
   not evidence a process stopped.
5. In an owner-authorized configuration PR set mode to `pilot` and `pilot_tasks` to
   the two selected issue numbers. Observation does not grant tasks. Complete
   two small nonconflicting tasks, one per host, through fresh review,
   serial integration, merged-main verification and private candidate creation.
   Only then switch the configured rollout mode to active.

Authentication and private Project access may require the owner. Agents should
prepare the precise configuration and report these missing prerequisites together;
they must not silently claim enforcement is active. Existing Codex access and
GitHub Actions/artifact quotas still apply; keep paid overage disabled.

The controller checks ownership/scope, CI, independent review, resolved review
conversations, and configured-owner authorization of sensitive frozen task scope
before serial merging and merged-main verification. GitHub Free does not itself
block direct pushes, manual
merges around the controller, force pushes/deletion, or concurrent main changes
outside this path. Both humans and agents must follow the repository protocol;
these controller safeguards cannot prevent a writer from bypassing it.

Eligible owners may optionally choose `integration_enforcement: "github"` in a
owner-authorized policy PR and apply protections with
`python scripts/setup_automation.py --apply --protections`. That mode fails closed
if the required protections are missing or unverifiable. It is not required for
routine automatic integration in the default controller mode.

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
include `--payload FILE` for JSON request fields, `--task NUMBER`, `--epoch EPOCH`, `--host HOST`, and `--session SESSION`. Run `--help` and each
command's help; extra request fields are supplied as JSON. Commands are:

| Command | Purpose |
| --- | --- |
| `doctor` | Check auth, tools, environment, data availability and coordination prerequisites |
| `register` | Declare authenticated worker, host/session and capability/input hashes |
| `next` | Request the highest-priority eligible nonconflicting task |
| `checkpoint` | Preserve branch, evidence and progress; renew ownership |
| `heartbeat` | Renew using an edited status comment without a workflow per heartbeat |
| `extend-scope` | Obtain extra path/resource reservations before changing scope |
| `submit` | Submit the granted task and exact PR revision for review |
| `review-next` | Reserve an independent review |
| `review-result` | Submit exact-head/base/spec verdict, findings and limitations |
| `release` | Checkpoint and release eligible code work |
| `recover` | Adopt interrupted work only with required preservation/process evidence |
| `recover-merged` | Authorize audited recovery of an externally merged, fenced task |
| `status` | Read queue, reservations and blockers |

Requests use a unique request ID and fenced JSON marked `agent-request:v1` on an
issue. Retry a request with the **same ID**. The confirmed grant binds actor,
host/session, ownership epoch, spec hash, base revision, paths and resources.
Never start from a board label or an unconfirmed claim. Revalidate ownership
before resuming, changing shared state, or publishing. A newer ownership epoch
invalidates old submissions.

A three-hour lease renews at checkpoints and before long operations. A stale
lease enters recovery rather than immediately assigning duplicate work.
For expired code-only work, another registered collaborator can recover with the
current epoch and a checkpoint naming the original granted remote branch and its
verified head SHA. The old epoch is fenced. Resource/input-bearing work retains
the original-host process/Store/artifact proof requirement; an offline host is
never assumed stopped.
Before yielding, record the branch/PR, exact revision, tests, remaining work and
artifact references. Review needs a fresh session, frozen spec, PR head and base;
a self-declared second verdict in the implementation session is insufficient.
Review responses echo the grant's `review_epoch` separately from task `epoch`,
with `verdict` set to `approve` or `changes` in the `--payload` JSON.

Inference changes also submit `native_evidence` containing `code_sha` equal to
the PR head, `source_sha256`, `model_sha256`, `receipt_sha256`, and a nonempty
`limitations` array. Receipts establish provenance and exercised behavior, not
independent annotation accuracy.

For submission, payload fields include integer `pr_number`, `spec_hash`, and
`head_sha`/`base_sha`. A review response additionally supplies `review_epoch`,
`findings`, `reviewed_files`, `limitations`, and `evidence` arrays. Reviewed files
and evidence cannot be empty. A review session registers with the same host and
a new `--session` value; it must actually be a fresh read-only agent session.

Use `checkpoint --task N --epoch E --payload FILE` with a `checkpoint` object.
Before long work renew ownership; heartbeat comments are collected by the hourly
watchdog, so use a normal checkpoint when an immediate acknowledgement matters.
No background worker is installed by this setup.

Code and base changes invalidate review evidence. Three failed repair rounds
escalate once with a clear blocker. Routine work can merge automatically after
CI and fresh independent agent review. Automation/security policy,
credentials/authentication, destructive migrations, deployment and model-promotion
scope requires explicit configured-owner authorization of the frozen task via
`human-approved`. Freeze such work as risk-human before claiming it. The scope
authorization is distinct from final PR review; the PR author may also be the
authorizing owner. Non-author human PR review is optional. Requested changes
and unresolved review threads remain vetoes. CI passing does not establish
badminton accuracy.

## Research, interrupted jobs and candidate delivery

Pin `BADMINTON_ROOT` and `BADMINTON_DATA_DIR` before importing configuration in
copied launchers. Use disposable test storage, and preserve actual annotations
and original predictions. GitHub experiment reservations complement the real
shared Store's `run_local_job` GPU admission; isolated Stores must not allow
competing work. A Windows CUDA requirement cannot silently fall back to Mac CPU.

Before recovering a GPU/data task, verify original-host PID, creation time,
working directory, command, Store/job state and durable artifacts. A timeout,
closed chat, offline host or absent observation handle does not prove exit.
Unreachable physical resources remain reserved until verified recovery.

Successful main verification creates SHA-addressed package/container candidates
using the reviewed `candidate_visibility` (`public` or `private`). Repository and
image visibility must match that explicit policy; the private Project remains
private in either mode. Running apps are not auto-upgraded. Raw datasets/videos, private
annotations, credentials, caches and external model weights remain excluded.
The publisher commit is frozen separately from the verified application source,
so older queued commits can use current reviewed publication controls without
changing the built source or its dependency-lock provenance. Image visibility
is checked before push and before a final digest receipt. Public mode requires
existing public GHCR packages, with any owner-only visibility transition handled
through [the owner checklist](OWNER_SETUP.md#candidate-visibility-and-public-builds).

Failed main verification pauses claims/merges and opens a repair task. Normal
notifications concern human action, integration/release failure, stalled
recovery or completed milestones.

### Externally merged task PRs

Routine PRs receive independent agent approval on their final head and then let
the controller perform serial integration. A writer merging around that sequence is an incident,
even when the resulting source is correct. A merged PR without its matching
integration journal is fenced into Recovery required. Its original grant,
submission, specification, independent review and observed merger/source remain
preserved. The controller records one incident and continues unrelated eligible
work; it does not infer approval from the merge or mark the task Done.

An explicitly authorized human approver can request `recover-merged` after
inspecting the actual source and recovery evidence. Use trusted merged-main
tools, register the real host/session, and supply a JSON payload with:

```json
{
  "pr_number": 114,
  "spec_hash": "ORIGINAL_FROZEN_SPEC_SHA256",
  "head_sha": "ORIGINAL_REVIEWED_HEAD_SHA",
  "base_sha": "ORIGINAL_REVIEWED_BASE_SHA",
  "merge_sha": "ACTUAL_MERGED_SOURCE_SHA",
  "evidence_state_sha": "IMMUTABLE_COORDINATION_COMMIT_WITH_ACCEPTED_REVIEW"
}
```

All commit fields must be actual lowercase 40-character SHAs. The evidence
commit must be an ancestor of the current `codex/coordination` branch and contain
the original accepted task grant, submission and independent approval. Locate it
through read-only coordination history, such as `git fetch origin
codex/coordination` and `git log FETCH_HEAD -- state.json`. Do not reconstruct a
verdict in the request body. This also supports a closed historical task whose
code-only recovery already archived its claim; keep that issue closed while
requesting adoption. Reopening and replanning it can replace the evidence needed
for recovery.

Use the task's **current fenced epoch**, while the source epoch remains separately
recorded in the historical evidence:

```sh
python scripts/agent_queue.py recover-merged --task 111 --epoch 2 --payload .cache/recover-merged.json --request-id UNIQUE_RECOVERY_ID
python scripts/agent_queue.py status --task 111
```

The first response is `recovery_pending`, not a grant or completion receipt. Only
the trusted controller can accept the recovery after rechecking the original
head/base/spec and branch, changed-file scope including renames, exact source
checks, independent review, unresolved conversations, actual merged-tree parity,
main ancestry and the latest complete successful exact merged-main workflow run
from trusted `main`. Missing, stale, failed or running evidence stays incomplete.
Existing current ownership cannot be displaced by an older evidence commit.

External adoption requires an authenticated configured-owner recovery request
and the original independent agent approval and source/CI evidence. Non-author
human review is optional. Actual GitHub reviews remain audit evidence. If the
owner has explicitly confirmed a personal review outside GitHub, the request may
add this optional separately typed attestation:

```json
{
  "human_review_attestation": {
    "kind": "owner_attestation",
    "reviewer": "ACTUAL_CONFIGURED_NON_AUTHOR_REVIEWER",
    "head_sha": "ORIGINAL_REVIEWED_HEAD_SHA",
    "statement": "The owner's explicit confirmation of who personally reviewed and approved this exact head."
  }
}
```

An agent may submit that field only with the owner's actual, exact-head
confirmation. A merge record, a scope authorization or an agent's guess cannot
supply it. The controller stores the authenticated authorizer and attestation
separately from GitHub reviews; it never creates an `APPROVED` review record.
Existing requested changes still block recovery. Omit the optional field when
no such review occurred; a malformed or conflicting supplied attestation is
rejected. Ordinary sensitive PRs require owner-authorized task scope, fresh
independent agent review and exact CI before controller merging.

Resource/input-bearing tasks additionally require the original-host
`terminal_proof` process lifetime, Store status and durable-artifact evidence used
by normal recovery. A merge, timeout or offline host does not establish process
exit. Code-only history recovery does not erase physical reservations. Unknown
or conflicting evidence leaves the task fenced with `external_recovery_error`.
Correcting a request requires a new request ID; never mutate a previously accepted
request or edit coordination state to bypass an error.

After successful adoption, the current ownership epoch stays fenced, the original
accepted review/source epoch and exact verification are retained in the audit,
and normal delivery outbox processing checks the complete candidate workflow.
An existing successful or live candidate is reused; adoption does not rerun
inference, deploy an app or promote a model. Completion and delivery are still
separate receipts.

## Retrospective history and Project synchronization

Preview before applying remote backfill:

```sh
python scripts/backfill_project.py --dry-run --revision cc1a37b
python scripts/backfill_project.py --apply --create-project --revision cc1a37b
# Or reuse an already configured Project:
python scripts/backfill_project.py --apply --project-number 1 --revision cc1a37b
```

Keep `--revision cc1a37b` for this initial history: later bootstrap merges are
not part of its qualified historical baseline. Ongoing task completion is handled
by the queue.

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
issue cards (and repairs unset Status after an interruption); coordination
automation uses `sync_board(..., preserve_existing=False)` to project authoritative
queue status. Ongoing queue status projection is owned by coordination automation,
not retrospective backfill. Neither tool grants ownership.

## Failed integration and publishing

A failed, cancelled, skipped or approval-blocked main verification pauses normal
work and creates one bounded repair issue. Only that coordinator-authorized
repair can acquire overlapping code paths while paused; physical research
resources stay protected. A verified repair records the original failed SHA and
repair SHA separately and resumes the queue. A repair that breaks main again
escalates once for human attention.

Sensitive or risk-human repairs enter Needs human with their own frozen scope.
An authenticated configured owner authorizes that exact repair hash using
`human-approved` before claiming; the parent's authorization is not reused.
The repair retains its paused-queue priority and `repair_for` linkage through
authorization, independent review and verified integration. Nonsensitive routine
repairs remain automatic. No non-author human PR approval is required.

Candidate publishing stays pending until the complete candidate workflow succeeds,
including package/image artifacts. Failed publishing is retried up to three
attempts, then produces one incident issue. A dispatch acknowledgement is not
proof of a completed release. Running app/data upgrades remain explicit.
