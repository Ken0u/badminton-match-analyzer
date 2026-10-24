# Controller merge follow-through

Issue [#232](https://github.com/Ken0u/badminton-match-analyzer/issues/232),
October 24, 2026. This bounded repair starts exact-main verification after a
confirmed controller merge during the same controller invocation. It retains
the existing merge journal, verification and delivery paths.

## Reproduced gap and event evidence

Baseline `c7108f599f453b091bb7fe580d52173a060345c9` returns immediately after
the journalled squash-merge request. An unchanged-source generated transport
reproduction using `optional_merge_setup()` recorded:

| Controller invocation | Merged PR | Task status | Cumulative main CI dispatches |
| --- | --- | --- | --- |
| First | Confirmed in fake transport | integrating | 0 |
| Second, ordinary invocation | Confirmed again | verifying_main | 1 |

No real merge, credential, media, label or model was used. Baseline source
SHA-256 is `a35b25346536c6c42b4a9dfd168518b51eaa6bfc523a2b1fea723d25dc7dcec0`
for the coordinator and
`c77ec8d8c8e3525279917396d813979e7244c54ccb031139e0baeafea1a18191`
for its test module. The local sealed reproduction is
`.cache/merge232-before-v1/reproduction.json`; clones can reproduce the two
calls using the baseline test fixture. Private local receipts are not supplied
by a clone.

The [GitHub workflow triggering documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow)
states that repository `GITHUB_TOKEN` operations suppress subsequent workflow
runs for events including push and PR closed. Explicit workflow dispatch is
an exception. This supports the post-merge gap: a token-created merge cannot
be relied upon to create the next invocation that dispatches main CI.

Two recent delivered tasks required normal verification wakes, without CI
retries or manual merges:

| Task | Controller merge | Exact PR CI | Exact main CI |
| --- | --- | --- | --- |
| [#228 / PR #229](https://github.com/Ken0u/badminton-match-analyzer/issues/228) | `4f0a93b0a952bd0d256cb602b915d5a299cc63b0` | [40090473105](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40090473105) | [40091123085](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40091123085) |
| [#230 / PR #231](https://github.com/Ken0u/badminton-match-analyzer/issues/230) | `c7108f599f453b091bb7fe580d52173a060345c9` | [40092448252](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40092448252) | [40093243758](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40093243758) |

Their issue completion records retain the separate public-delivery verification.
These observations support the merge-to-verification repair. They do not
establish a cause or repair for publishing-completion event observations.

## Bounded behavior

After the existing gates permit a journalled merge, a successful response with
a valid merge SHA permits one confirmation-only follow-through. It re-reads
trusted coordination state and the actual PR, retaining the original claim,
submission, scope and integration journal. Concurrent task changes defer to
an ordinary invocation. The actual PR must be merged, identify the expected
repository/PR/main branch and source, and match the original head/base/spec
journal binding. Main must still equal that observed merge. The response
alone never authorizes adoption or CI dispatch.

The follow-through selects only the just-merged task and cannot enter the
open-PR merge path. It skips unrelated recovery and delivery outboxes. It
rechecks the task and main after reading CI, then reuses the existing
`verify-main` transition and dispatch/delivery/failed-main behavior. Queued,
running, successful and failed exact-source runs are reused; known matching
runs cause no extra CI dispatch or implicit failed-job retry. Source identity
remains separate from workflow execution and tested/main/publisher identities.

A stale, missing or mismatched confirmation leaves the journal intact without
inventing an external-merge incident in that follow-through. An ordinary later
invocation retains its stricter historical external-merge fencing. Lost merge
responses and adapter failures preserve durable state for ordinary recovery;
there is no automatic network retry added here. Optional code review, actual
requested-changes vetoes, source/scope/owner authorization, exact CI, ancestry,
conversation, native-evidence and serial merge checks remain in force.

## Verification and limits

Generated regressions exercise immediate exact-main dispatch without another
event, one merge only with a second eligible task, queued/running/successful/
failed CI reuse, stale and mismatched PR observations, changed task/epoch/main,
malformed and lost responses, adapter failures and later journalled recovery.
Existing policy-veto and external-merge tests remain. Required focused/full
Python, lint, formatting, dependency, repository and whitespace checks are
recorded on the owning issue before submission; exact PR/main CI and complete
public delivery are required separately.

The implementation PR itself is merged by the previous trusted controller;
its own verification may still need a normal wake. Generated evidence does
not establish prospective live execution of the new follow-through. That
requires a later real controller merge. GitHub reads, state commits and network
effects are not an atomic transaction. An unobserved dispatch or lost network
response can still require an ordinary recovery invocation; this repair does
not claim exactly-once dispatch under eventual consistency or external writers.

Only the coordinator, its tests and this report change. Workflow permissions,
credentials, configuration, CI checks/time limits/retry rules and scientific
eligibility remain unchanged. No application/model deployment, research rerun
or badminton accuracy improvement is established.
