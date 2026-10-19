# Owner activation checklist

Implementation and issue history are available before activation. This is a
one-time setup by `Ken0u`; `dootz1` currently has write rather than admin access.
No subscription, credentials or branch protections were changed by this PR.

1. Review and merge the bootstrap DevOps PR after its exact-head CI succeeds.
   This change alters trusted workflows/policy and requires non-author human
   review. Keep `.github/automation.json` in observation mode.
2. Enable the GitHub plan supporting protected branches in this private personal
   repository. Run `python scripts/setup_automation.py --apply --protections`
   while authenticated as the owner. The script previews configuration without
   `--apply`; it never bypasses subscription or admin requirements.
3. Authenticate a Project-capable owner credential locally, then run
   `python scripts/backfill_project.py --apply --create-project`. The script
   reuses the existing 43 backfill issues and exact-title private Project;
   interrupted runs can be repeated. The initial history source is `cc1a37b`.
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
   to `active`. Owner billing should retain zero paid overage unless explicitly
   authorized separately. Local workers stop when both computers/Codex sessions
   are unavailable; GitHub is not an always-on inference service.

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
Project scope. GitHub also reported that private rulesets require an upgrade.

Once active, routine task administration, review, merging and candidate builds
are automatic. Human decisions remain for scope changes, sensitive approvals,
annotation adjudication, spending and exceptional recovery.
