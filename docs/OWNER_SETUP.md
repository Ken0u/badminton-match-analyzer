# Owner activation checklist

Implementation and issue history are available before activation. This is a
one-time setup by `Ken0u`; `dootz1` currently has write rather than admin access.
GitHub Pro is not required. The default `integration_enforcement: "controller"`
works with public or private repositories on GitHub Free. No subscription or
branch-protection setup is required. Candidate visibility is configured separately
from the private Project, as described below.

1. Review and merge the bootstrap DevOps PR after its exact-head CI succeeds.
   The owner authorizes this initial trusted workflow/policy setup. Keep
   `.github/automation.json` in observation mode.
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
6. Select two small nonconflicting issues, one per host. In an owner-authorized
   configuration PR set `mode` to `pilot` and `pilot_tasks` to their issue numbers.
   Verify committed grants, independent reviews, sequential merges, merged-main
   checks, board updates and candidate artifacts matching the declared visibility.
7. After both pilots pass, use an owner-authorized configuration PR to change mode
   to `active`. GitHub Actions and artifact/storage quotas still apply; keep
   paid overage disabled unless explicitly authorized separately. Each collaborator
   uses their existing Codex access and its usage limits. Local workers stop when
   both computers/Codex sessions are unavailable; GitHub is not an always-on inference service.

The two rollout PRs are a narrow bootstrap exception to queue ownership: they
may change only `mode` and `pilot_tasks` in `.github/automation.json`. Trusted
main code publishes `automation/policy` after current CI and resolved review
conversations. A human performs the explicitly authorized merge of these two
PRs; a second human's PR approval is optional. No other policy,
workflow or credential change qualifies, and the rollout path never auto-merges.
This permits activation while observation mode correctly grants no tasks.

Historical records live in [Issues](https://github.com/Ken0u/badminton-match-analyzer/issues).
[Queue control #74](https://github.com/Ken0u/badminton-match-analyzer/issues/74)
accepts durable requests after the trusted controller is merged. Project creation
requires a Project-capable credential; ordinary repository authentication alone
may not provide that scope. The board stays private even when source and build
artifacts are public. Project authorization does not require buying GitHub Pro.

## Candidate visibility and public builds

The reviewed `.github/automation.json` declares `candidate_visibility` as `public`
for this public repository. Private installations use `private`. Missing, invalid
or mismatched repository visibility stops publishing; the workflow never silently
falls back to another mode. The legacy workflow name **Private candidates** is
retained for controller receipt compatibility; receipts record actual visibility.

Public mode makes the wheel/sdist workflow artifacts and the `review`/`cpu`
container images public. It does not publish the private Project, credentials,
datasets, uploaded videos, private annotations, caches or external model weights,
and it does not deploy or upgrade a running application.
Visibility does not choose a project license or change dependency terms; the
[existing license inventory](DEPLOYMENT.md#dependency-licenses-and-source) remains
applicable to distribution.

GHCR package visibility is independent of source-repository visibility. An owner
must set both `badminton-match-analyzer-review` and
`badminton-match-analyzer-cpu` to Public in their package settings before public
pushes can succeed. A missing public package requires an owner-controlled initial
package setup; the publisher refuses to assume it is public. Changing a package
to public cannot be reversed, so this follows the owner's explicit publication
decision. See [GitHub's package visibility instructions](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).
Private mode permits initial package creation using GHCR's private default and
requires confirmed private visibility in the final image receipt. Both modes
check visibility before pushing and again before recording success.

The publisher is frozen at a reviewed main commit during eligibility. Both the
application source and publisher require successful exact merged-main checks;
an older verified source cannot authorize an unverified publisher. Package
and image jobs check out that publisher separately from the exact verified
application source. Receipts bind both commits; the dependency lock hash belongs
to the application source. This supports older queued sources without running
their obsolete publishing helper or including the publisher checkout in builds.

After a reviewed publisher repair, rerunning an old failed workflow still uses
its old workflow definition. For a terminal failed candidate with no successful
delivery, dispatch the current trusted `release.yml` on `main` once with its
original verified `source_sha`. First check for an existing successful or live
candidate for that source. Do not reset attempt counters, edit coordination
state, bypass CI, or repeat inference. The normal delivery outbox recognizes the
new complete successful candidate and clears its pending/error state. Partial
package or image success is insufficient.

## Integration safeguards without Pro

The controller checks task ownership and scope, CI, independent exact-head/base
review, resolved review conversations, and configured-owner authorization of
sensitive frozen task scope before serial integration. It verifies the merged
main commit and pauses work on failure.
Both collaborators and their agents must use this path. GitHub Free does not
prevent a writer from pushing directly to `main`, manually bypassing these checks,
force pushing/deleting the branch, or changing main concurrently outside the
controller. These actions are prohibited by the repository protocol; controller
checks cannot provide the server-side backstop of protected branches.

Owners who already have eligible branch protection may opt into
`integration_enforcement: "github"` in an owner-authorized policy PR and run
`python scripts/setup_automation.py --apply --protections`. That mode refuses
integration if its required protections are absent or cannot be verified. It is
optional; do not upgrade a subscription solely to complete this checklist.

Once active, routine task administration, review, merging and candidate builds
are automatic. Human decisions remain for scope changes, sensitive task scope,
annotation adjudication, spending and exceptional recovery. Final task PR review
uses fresh independent agent approval and exact CI without requiring a non-author
human PR approval. Existing requested changes and unresolved threads still veto
integration.
