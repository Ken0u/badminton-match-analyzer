# Owner activation checklist

Implementation and issue history are available before activation. This is a
one-time setup by `Ken0u`; `dootz1` currently has write rather than admin access.
GitHub Pro is not required. The default `integration_enforcement: "controller"`
works with a private repository on GitHub Free. No subscription, credentials or
branch protections were changed by this PR.

1. Review and merge the bootstrap DevOps PR after its exact-head CI succeeds.
   This change alters trusted workflows/policy and requires non-author human
   review. Keep `.github/automation.json` in observation mode.
2. Run `python scripts/setup_automation.py --apply` while authenticated as the
   owner. Keep `integration_enforcement` set to `controller`; no paid plan or
   branch-protection setup is needed. The script previews configuration without
   `--apply`. Confirm both collaborators have write access.
3. Authenticate a Project-capable owner credential locally, then run
   `python scripts/backfill_project.py --apply --create-project --revision cc1a37b`.
   The script reuses the existing 43 backfill issues and exact-title private Project;
   interrupted runs can be repeated. Keep `--revision cc1a37b` when repeating
   this initial backfill so the bootstrap merge is not mistaken for part of the qualified historical baseline.
4. Set repository variable `AGENT_PROJECT_NUMBER` to the resulting number and
   secret `AGENT_PROJECT_TOKEN` to a credential with Project read/write and the
   required private-repository read access. Use GitHub's secret input; never
   commit or paste the credential into a chat/issue. It is used only by trusted
   main-code projection, never PR test code. Do not upload Codex credentials.
5. Both collaborators authenticate their own GitHub account and start a local
   Codex goal using [the collaboration guide](COLLABORATION.md). Bootstrap new
   task worktrees with the pinned tool/environment profiles. Existing application
   environments and Windows research jobs are not migrated or restarted.
6. Select two small nonconflicting issues, one per host. In a human-reviewed
   configuration PR set `mode` to `pilot` and `pilot_tasks` to their issue numbers.
   Verify committed grants, independent reviews, sequential merges, merged-main
   checks, board updates and private candidate artifacts.
7. After both pilots pass, use a human-reviewed configuration PR to change mode
   to `active`. GitHub Actions and artifact/storage quotas still apply; keep
   paid overage disabled unless explicitly authorized separately. Each collaborator
   uses their existing Codex access and its usage limits. Local workers stop when
   both computers/Codex sessions are unavailable; GitHub is not an always-on inference service.

The two rollout PRs are a narrow bootstrap exception to queue ownership: they
may change only `mode` and `pilot_tasks` in `.github/automation.json`. Trusted
main code publishes `automation/policy` after current CI and a current-head
non-author human approval. A human merges these two PRs. No other policy,
workflow or credential change qualifies, and the rollout path never auto-merges.
This permits activation while observation mode correctly grants no tasks.

Historical records live in [Issues](https://github.com/Ken0u/badminton-match-analyzer/issues).
[Queue control #74](https://github.com/Ken0u/badminton-match-analyzer/issues/74)
accepts durable requests after the trusted controller is merged. Project creation
was not possible with the implementation account's current token: it lacks the
Project scope. This authorization is still needed for the board; it does not
require buying GitHub Pro.

## Integration safeguards without Pro

The controller checks task ownership and scope, CI, independent exact-head/base
review, resolved review conversations, and sensitive-change human approval before
serial integration. It verifies the merged main commit and pauses work on failure.
Both collaborators and their agents must use this path. GitHub Free does not
prevent a writer from pushing directly to `main`, manually bypassing these checks,
force pushing/deleting the branch, or changing main concurrently outside the
controller. These actions are prohibited by the repository protocol; controller
checks cannot provide the server-side backstop of protected branches.

Owners who already have eligible branch protection may opt into
`integration_enforcement: "github"` in a human-reviewed policy PR and run
`python scripts/setup_automation.py --apply --protections`. That mode refuses
integration if its required protections are absent or cannot be verified. It is
optional; do not upgrade a subscription solely to complete this checklist.

Once active, routine task administration, review, merging and candidate builds
are automatic. Human decisions remain for scope changes, sensitive approvals,
annotation adjudication, spending and exceptional recovery.
