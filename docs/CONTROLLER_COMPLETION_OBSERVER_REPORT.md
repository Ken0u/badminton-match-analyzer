# Bounded controller completion observation

Prepared October 24, 2026 for issue #235, following delivered #232 and #220.

The controller already confirms its own journalled squash merge and dispatches
exact-main CI in the same invocation. Two later boundaries still needed ordinary
controller wakes: successful-main reconciliation and publishing acknowledgement.
This increment adds a separate bounded observer that wakes the existing
controller after observing an exact terminal workflow run. The controller retains
all authority over checks, integration, recovery and publication retries.

## Observed baseline

Baseline source is `6496a1a9cd48b7fa43b641c5479ceedbedd25ea0`. During #220,
controller run `40102127452` integrated PR #234 at 14:24:13 UTC and dispatched
exact-main verification at 14:24:27 UTC in the same invocation. Main CI
`40102348799` passed; ordinary wake `40102985199` reconciled it and started
publisher `40103082482`. That publisher passed; wake `40103328997` acknowledged
complete delivery. No CI or publishing retry was needed.

GitHub documents [token-triggered event suppression and dispatch exceptions](https://docs.github.com/en/actions/concepts/security/github_token).
Its [workflow events reference](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
also describes workflow-run chaining limits. These documents do not establish
why this repository's later completion events were absent. That cause remains
unproven; this change supplies an independent bounded wake path.

## Behavior and boundaries

After successful integration, the normal trusted controller launches observers
for journalled `verifying_main` tasks and `done` tasks with pending delivery.
Launch and observation read coordination but never write it. Each observer pins
an immutable coordination-history revision, task, epoch, source, stage and
existing delivery attempt. It checks the frozen specification, original grant,
submission, integration journal, actual merged PR and main ancestry. It checks
current evidence before observation and again before dispatch. Unsupported
external-recovery and repair-adopted tasks retain the existing recovery path.

Main CI matches the trusted `ci.yml` workflow, repository, main branch and exact
push source or `Verify <source>` dispatch title. Publication matches trusted
`release.yml` on main with its historical `Private candidate <source>` title.
The observer pins run ID and attempt and re-reads terminal evidence. It does not
receive a caller-supplied success flag. Success, failure and cancellation all
wake the same ordinary controller; only that controller interprets the result.
Publication failure can exercise only the pre-existing three-attempt delivery
policy. No retry is added by the observer.

The workflow checks out main with credential persistence disabled and passes
inputs through environment variables. It has contents-read and actions-write,
with no Project token, new secret or contents/issue/PR write permission. The
entrypoint requires its exact trusted main Actions workflow. Its transport
allows only reads and one fixed dispatch destination per command: the launcher
can dispatch the observer, and the observer can dispatch the normal controller.
Neither can rerun CI/publishing, merge a PR or mutate coordination through that
transport. Existing workflow permissions and controller/CI/publisher code are
unchanged.

Each observer has a 90-minute transport/poll deadline, individual requests of at
most 20 seconds, 30-second polling and a 95-minute workflow limit. This allows
the current 35-minute CI jobs and sequential 5/20/45-minute publication stages
without extending them. The launch step has a separate two-minute transport
deadline. Waiting happens outside the controller's serialized concurrency group.
Active controller lifetimes, including the originating run and PR-target runs,
are observed before dispatch; source/run evidence is rechecked after waiting.

The launcher reuses matching queued, running and terminal observers. Deterministic
run names/concurrency include task, epoch, stage, source and delivery counter.
Listings and target counts are bounded; incomplete, malformed or oversized
results fail conservatively. API errors, lost responses, changed attempts,
missing runs and deadlines remain unknown outcomes. There is no automatic
request retry. A known failed observer is not silently restarted. The existing
completion events and hourly controller schedule remain fallback paths.

This is not an exactly-once network transaction. Lost responses followed by
temporarily invisible runs can produce duplicate observer dispatches, and an
ordinary controller may start between the last lifetime read and dispatch.
Concurrency and repeated task/source checks limit overlap; duplicate normal
wakes still pass through unchanged controller policy. Timeout/unknown logs
cannot establish completion or success. Public Actions logs contain process
metadata and aggregate observations, never research inputs or credentials.

## Verification and remaining evidence

Generated tests exercise the real queue/controller state machine with a fake
GitHub transport. They cover both stages, pending/terminal transitions, failure
and cancellation, source/identity mismatches, stale grants and actual PRs,
history membership, active-controller waits, exhausted delivery, duplicate
observer reuse, uncertain dispatches, timeout bounds, transport restrictions
and trusted entrypoint/workflow boundaries. An initial focused run exposed an
overly strict authorization check for routine tasks; it was corrected to follow
the existing sensitive-scope policy. No real privileged candidate code was run
with credentials before integration.

Final local checks and exact PR/main CI remain required before completion.
The implementation PR initially uses old trusted automation. Generated behavior
does not prove prospective live observation; any normal wakes needed for this
transition and later real observer evidence must be recorded on #235. Independent
public package and both-image delivery verification remains required.

No research data, images, labels, predictions, holdout, model, inference or
training was accessed. Complete-rally references remain 0/2, all 1,532 source
frames/unknowns are preserved, and no training-ready row or improvement in
badminton annotation accuracy is established by this automation work.
